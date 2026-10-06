//! Native-only GitHub update contract. Legacy Python archives are never installed.
use super::*;
use std::os::{fd::AsRawFd, unix::fs::PermissionsExt};

const REPO: &str = "RedGry/helios-container";
const ASSET: &str = "helios-container-freebsd-amd64";

fn version(value: &str) -> Result<(u64, u64, u64)> {
    let value = value.strip_prefix('v').unwrap_or(value);
    let parts: Vec<_> = value.split('.').collect();
    if parts.len() != 3
        || parts.iter().any(|s| {
            s.is_empty()
                || !s.bytes().all(|b| b.is_ascii_digit())
                || (s.len() > 1 && s.starts_with('0'))
        })
    {
        return Err("Ожидается стабильная версия X.Y.Z".into());
    }
    Ok((parts[0].parse()?, parts[1].parse()?, parts[2].parse()?))
}
fn installed(base: &Path) -> Result<String> {
    match fs::read_to_string(base.join("VERSION")) {
        Ok(v) => {
            let v = v.trim().to_owned();
            version(&v)?;
            Ok(v)
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok("0.0.0".into()),
        Err(e) => Err(e.into()),
    }
}
fn latest() -> Result<Option<Value>> {
    let out = Command::new("curl")
        .args([
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--connect-timeout",
            "5",
            "--max-time",
            "10",
            "--max-filesize",
            "1048576",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "User-Agent: helios-container",
            "--write-out",
            "\n%{http_code}",
            &format!("https://api.github.com/repos/{REPO}/releases/latest"),
        ])
        .output()?;
    if !out.status.success() {
        return Err("Не удалось получить сведения о релизе".into());
    }
    if out.stdout.len() > 1048600 {
        return Err("Ответ GitHub слишком большой".into());
    }
    let text = String::from_utf8(out.stdout)?;
    let (body, status) = text.rsplit_once('\n').ok_or("Некорректный ответ GitHub")?;
    if status == "404" {
        return Ok(None);
    }
    if status != "200" {
        return Err(format!("GitHub HTTP {status}").into());
    }
    let value: Value = serde_json::from_str(body)?;
    if value["draft"] == true || value["prerelease"] == true {
        return Ok(None);
    }
    version(value["tag_name"].as_str().ok_or("Нет версии релиза")?)?;
    Ok(Some(value))
}
fn asset(release: &Value, name: &str) -> Result<String> {
    let tag = release["tag_name"].as_str().ok_or("Нет тега")?;
    version(tag)?;
    let expected = format!("https://github.com/{REPO}/releases/download/{tag}/{name}");
    for item in release["assets"]
        .as_array()
        .ok_or("Нет списка файлов релиза")?
    {
        if item["name"] == name {
            if item["browser_download_url"] != expected {
                return Err("Неожиданный адрес файла релиза".into());
            }
            return Ok(expected);
        }
    }
    Err(format!("В релизе нет нативного файла {name}. Python-архив не устанавливается").into())
}
fn newer(base: &Path, release: &Value) -> Result<bool> {
    Ok(version(release["tag_name"].as_str().ok_or("Нет версии")?)? > version(&installed(base)?)?)
}
fn announce(base: &Path, release: Option<&Value>) -> Result<()> {
    println!("Установлена версия: {}", installed(base)?);
    if let Some(release) = release.filter(|r| newer(base, r).unwrap_or(false)) {
        let tag = release["tag_name"].as_str().unwrap_or_default();
        println!("Доступна версия: {tag}\nChangelog: https://github.com/{REPO}/releases/tag/{tag}");
    } else {
        println!("Новых стабильных релизов нет");
    }
    Ok(())
}
fn refresh_web(binary: &Path, base: &Path) -> Result<()> {
    // web install prints the private URL. Capture and discard it, including during rollback.
    short_output(
        Command::new(binary)
            .arg("--base")
            .arg(base)
            .args(["web", "install"]),
        Duration::from_secs(75),
    )?;
    Ok(())
}
fn apply(kit: &Kit, release: &Value) -> Result<()> {
    let base = super::install::safe_base(&kit.base)?;
    for name in ["helios-container-native", "VERSION", ".update.lock"] {
        super::install::no_links(&base.join(name))?;
    }
    if kit.pid().is_some() {
        return Err("Перед обновлением выполните helios-container stop".into());
    }
    let lock = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(base.join(".update.lock"))?;
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    if kit.pid().is_some() {
        return Err("VM запущена, обновление отменено".into());
    }
    let stage = base.join(format!(".native-update-{}", std::process::id()));
    fs::create_dir(&stage)?;
    fs::set_permissions(&stage, fs::Permissions::from_mode(0o700))?;
    let mut retain_backup = false;
    let result = (|| -> Result<()> {
        let binary = stage.join(ASSET);
        let checksum = stage.join("checksum");
        let marker = stage.join("VERSION");
        super::install::download(&asset(release, ASSET)?, &binary, 16 * 1024 * 1024)?;
        super::install::download(
            &asset(release, &format!("{ASSET}.sha256"))?,
            &checksum,
            4096,
        )?;
        super::install::download(&asset(release, "VERSION")?, &marker, 256)?;
        let text = fs::read_to_string(checksum)?;
        let parts: Vec<_> = text.split_whitespace().collect();
        if parts.len() != 2
            || parts[1] != ASSET
            || parts[0].len() != 64
            || !parts[0].bytes().all(|b| b.is_ascii_hexdigit())
            || super::install::digest(&binary, "sha256")? != parts[0].to_ascii_lowercase()
        {
            return Err("SHA-256 бинарника не совпадает".into());
        }
        let tag = release["tag_name"].as_str().ok_or("Нет версии")?;
        let expected_version = version(tag)?;
        if version(fs::read_to_string(&marker)?.trim())? != expected_version {
            return Err("VERSION не совпадает с тегом".into());
        }
        let bytes = fs::read(&binary)?;
        // ELF64 little-endian amd64, FreeBSD OSABI. Prevent accidental Linux asset installation.
        if bytes.len() < 64
            || &bytes[..4] != b"\x7fELF"
            || bytes[4] != 2
            || bytes[5] != 1
            || bytes[7] != 9
            || u16::from_le_bytes([bytes[18], bytes[19]]) != 62
        {
            return Err("Релиз не является FreeBSD amd64 ELF".into());
        }
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o700))?;
        let report = short_output(
            Command::new(&binary).arg("--build-version"),
            Duration::from_secs(5),
        )?;
        let expected = format!(
            "{}.{}.{}",
            expected_version.0, expected_version.1, expected_version.2
        );
        if !report
            .split_whitespace()
            .any(|p| p.trim_start_matches('v') == expected)
        {
            return Err("Версия бинарника не совпадает с релизом".into());
        }
        let target = base.join("helios-container-native");
        let old_version = base.join("VERSION");
        for (from, backup) in [
            (&target, stage.join("binary.before")),
            (&old_version, stage.join("version.before")),
        ] {
            if from.exists() {
                fs::copy(from, backup)?;
            }
        }
        let web_enabled = base.join("web.json").exists();
        // All remote data and the candidate executable have been verified before stopping the agent.
        if web_enabled {
            super::agent::stop(&base)?;
        }
        let replace = (|| -> Result<()> {
            fs::rename(&binary, &target)?;
            atomic(&old_version, format!("{expected}\n").as_bytes(), 0o600)?;
            if web_enabled {
                refresh_web(&target, &base)?;
            }
            Ok(())
        })();
        if let Err(error) = replace {
            let rollback = (|| -> Result<()> {
                if web_enabled {
                    super::agent::stop(&base)?;
                }
                for (name, backup, mode) in [
                    (&target, stage.join("binary.before"), 0o700),
                    (&old_version, stage.join("version.before"), 0o600),
                ] {
                    if backup.exists() {
                        atomic(name, &fs::read(backup)?, mode)?;
                    } else if name.exists() {
                        fs::remove_file(name)?;
                    }
                }
                if web_enabled && target.exists() {
                    refresh_web(&target, &base)?;
                }
                Ok(())
            })();
            if let Err(rollback_error) = rollback {
                retain_backup = true;
                return Err(format!("Обновление отменено: {error}. Восстановление не завершено: {rollback_error}. Резервная копия: {}", stage.display()).into());
            }
            return Err(
                format!("Обновление отменено, предыдущая версия восстановлена: {error}").into(),
            );
        }
        // Config, guest disks, routes and credentials are preserved. PHP and agent now match the binary.
        println!("Обновлено до {expected}. Запустите команду повторно");
        Ok(())
    })();
    if !retain_backup {
        let _ = fs::remove_dir_all(stage);
    }
    result
}
pub(super) fn run(kit: &Kit, args: &[String]) -> Result<()> {
    let check = args.first().is_some_and(|a| a == "check-update");
    if args.iter().skip(1).any(|a| a != "--yes") {
        return Err("update [--yes] или check-update".into());
    }
    let release = latest()?;
    announce(&kit.base, release.as_ref())?;
    let Some(release) = release.filter(|r| newer(&kit.base, r).unwrap_or(false)) else {
        return Ok(());
    };
    if check {
        return Ok(());
    }
    // Check contract before requesting approval. Existing Python-only releases are incompatible.
    for name in [ASSET, &format!("{ASSET}.sha256"), "VERSION"] {
        asset(&release, name)?;
    }
    if !args.iter().any(|a| a == "--yes") {
        if !io::stdin().is_terminal() {
            return Err("Для обновления выполните helios-container update --yes".into());
        }
        eprint!("Обновить сейчас? [y/N] ");
        io::stderr().flush()?;
        let mut answer = String::new();
        io::stdin().read_line(&mut answer)?;
        if !matches!(
            answer.trim().to_lowercase().as_str(),
            "y" | "yes" | "д" | "да"
        ) {
            return Ok(());
        }
    }
    apply(kit, &release)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn strict_versions() {
        assert_eq!(version("v1.2.3").unwrap(), (1, 2, 3));
        for value in ["1.2", "01.2.3", "1.2.3-beta", "1.2.3/evil", "1.2.-3"] {
            assert!(version(value).is_err());
        }
    }
    #[test]
    fn native_assets_only() {
        let release = json!({"tag_name":"v1.2.3", "assets":[{"name":ASSET,"browser_download_url":"https://attacker.invalid/binary"}]});
        assert!(asset(&release, ASSET).is_err());
        let release = json!({"tag_name":"v1.2.3", "assets":[]});
        assert!(asset(&release, ASSET).is_err());
    }
}
