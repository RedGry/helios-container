//! User-only FreeBSD installation. No interpreter or system package mutation.
use super::*;
use std::os::unix::fs::PermissionsExt;

const IMAGE: &str = "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/alpine-3.24.2-x86_64-cloudinit-r0.qcow2";
const IMAGE_SHA: &str = "c9504d23613f304e0cfb6f5fec872e29e5a5a62e2bc64796daf19c14fdddaa87dc252912fd8bdd17f7b8ebf0cd03305e4075993d54de175e6028d6b50414c67f";

pub(super) fn no_links(path: &Path) -> Result<()> {
    let mut current = PathBuf::new();
    for part in path.components() {
        if matches!(part, std::path::Component::ParentDir) {
            return Err("Путь не должен содержать ..".into());
        }
        current.push(part);
        if let Ok(meta) = fs::symlink_metadata(&current) {
            if meta.file_type().is_symlink() {
                return Err(format!("Ссылка в пути: {}", current.display()).into());
            }
        }
    }
    Ok(())
}
pub(super) fn safe_base(path: &Path) -> Result<PathBuf> {
    let home = PathBuf::from(env::var("HOME")?).canonicalize()?;
    let path = if path.is_absolute() {
        path.to_owned()
    } else {
        env::current_dir()?.join(path)
    };
    no_links(&path)?;
    if !path.starts_with(&home) || path == home {
        return Err("Каталог должен находиться внутри HOME".into());
    }
    Ok(path)
}
pub(super) fn download(url: &str, path: &Path, limit: u64) -> Result<()> {
    if !url.starts_with("https://") {
        return Err("Загрузка требует HTTPS".into());
    }
    no_links(path)?;
    checked(
        Command::new("curl")
            .args([
                "--fail",
                "--location",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--retry",
                "3",
                "--connect-timeout",
                "15",
                "--max-time",
                "300",
                "--max-filesize",
                &limit.to_string(),
                "--output",
            ])
            .arg(path)
            .arg(url),
    )?;
    if fs::metadata(path)?.len() > limit {
        return Err("Размер загрузки превышает лимит".into());
    }
    Ok(())
}
pub(super) fn digest(path: &Path, algorithm: &str) -> Result<String> {
    Ok(output(Command::new(algorithm).arg("-q").arg(path))?
        .trim()
        .to_owned())
}

fn files(root: &Path) -> Result<Vec<PathBuf>> {
    let mut result = Vec::new();
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if fs::symlink_metadata(&path)?.is_dir() {
            result.extend(files(&path)?);
        } else {
            result.push(path);
        }
    }
    Ok(result)
}
fn copy_payload(source: &Path, unpacked: &Path, minimal: &Path) -> Result<()> {
    let target = minimal.join(source.strip_prefix(unpacked)?);
    fs::create_dir_all(target.parent().ok_or("Нет родительского каталога")?)?;
    let resolved = source.canonicalize()?;
    if !resolved.starts_with(unpacked) {
        return Err("Пакет ссылается за пределы распаковки".into());
    }
    fs::copy(resolved, target)?;
    Ok(())
}
fn package_path_allowed(name: &str) -> bool {
    let path = Path::new(name);
    !path
        .components()
        .any(|part| matches!(part, std::path::Component::ParentDir))
        && (!path.is_absolute()
            || path
                .strip_prefix("/")
                .is_ok_and(|relative| relative.starts_with("usr/local")))
}
fn qemu(base: &Path) -> Result<()> {
    let target = base.join("qemu");
    no_links(&target.join(".complete"))?;
    if target.join(".complete").is_file() {
        if fs::read_to_string(target.join(".complete"))?.trim() != "FreeBSD:14:amd64 qemu-nox11" {
            return Err("Некорректный маркер QEMU. Каталог сохранён".into());
        }
        for name in ["qemu-system-x86_64", "qemu-img"] {
            let binary = target.join("usr/local/bin").join(name);
            no_links(&binary)?;
            if !binary.is_file() {
                return Err("Незавершённая установка QEMU. Каталог сохранён".into());
            }
        }
        return Ok(());
    }
    if target.exists() {
        return Err(
            "Незавершённый каталог qemu сохранён. Переместите его перед повторной установкой"
                .into(),
        );
    }
    let work = base.join(format!(".packages-{}", std::process::id()));
    fs::create_dir(&work)?;
    let result = (|| -> Result<()> {
        for name in ["repos", "db", "cache", "downloads", "unpacked", "minimal"] {
            fs::create_dir(work.join(name))?;
        }
        atomic(&work.join("repos/FreeBSD.conf"), b"FreeBSD: { url: \"https://pkg.FreeBSD.org/FreeBSD:14:amd64/latest\", enabled: yes, signature_type: \"fingerprints\", fingerprints: \"/usr/share/keys/pkg\" }\n", 0o600)?;
        let pkg = |verb: &str| {
            let mut cmd = Command::new("pkg");
            for value in [
                format!("REPOS_DIR={}", work.join("repos").display()),
                format!("PKG_DBDIR={}", work.join("db").display()),
                format!("PKG_CACHEDIR={}", work.join("cache").display()),
                "INSTALL_AS_USER=true".into(),
            ] {
                cmd.arg("-o").arg(value);
            }
            cmd.arg(verb);
            cmd
        };
        println!("Скачиваю подписанные пакеты QEMU…");
        checked(&mut pkg("update"))?;
        checked(
            pkg("fetch")
                .args(["-y", "-d", "-o"])
                .arg(work.join("downloads"))
                .arg("qemu-nox11"),
        )?;
        let archives: Vec<_> = files(&work.join("downloads"))?
            .into_iter()
            .filter(|p| p.extension().is_some_and(|s| s == "pkg"))
            .collect();
        if archives.is_empty() {
            return Err("pkg не сохранил пакеты".into());
        }
        let unpacked = work.join("unpacked").canonicalize()?;
        for archive in archives {
            let listing = output(Command::new("tar").arg("-tf").arg(&archive))?;
            for name in listing.lines() {
                if !package_path_allowed(name) {
                    return Err(format!("Небезопасный путь в пакете: {name}").into());
                }
            }
            checked(
                Command::new("tar")
                    .args(["--no-same-owner", "-xf"])
                    .arg(archive)
                    .arg("-C")
                    .arg(&unpacked)
                    .args(["--exclude", "+*"]),
            )?;
        }
        let minimal = work.join("minimal").canonicalize()?;
        for name in ["qemu-system-x86_64", "qemu-img"] {
            copy_payload(
                &unpacked.join("usr/local/bin").join(name),
                &unpacked,
                &minimal,
            )?;
        }
        for path in files(&unpacked.join("usr/local/lib"))? {
            let relative = path.strip_prefix(unpacked.join("usr/local/lib"))?;
            let name = path.file_name().unwrap_or_default().to_string_lossy();
            if (relative.components().count() == 1 && name.contains(".so"))
                || relative.starts_with("qemu")
            {
                copy_payload(&path, &unpacked, &minimal)?;
            }
        }
        for entry in fs::read_dir(unpacked.join("usr/local/share/qemu"))? {
            let path = entry?.path();
            let name = path.file_name().unwrap_or_default().to_string_lossy();
            if (name.starts_with("bios") || name.starts_with("vgabios")) && name.ends_with(".bin")
                || name == "kvmvapic.bin"
            {
                copy_payload(&path, &unpacked, &minimal)?;
            }
        }
        let lib = minimal.join("usr/local/lib");
        let modules = lib.join("qemu");
        let binaries: Vec<_> = files(&minimal.join("usr/local/bin"))?
            .into_iter()
            .chain(if modules.exists() {
                files(&modules)?
            } else {
                vec![]
            })
            .collect();
        let mut keep = std::collections::HashSet::new();
        for binary in binaries {
            let listing = output(
                Command::new("ldd")
                    .arg(binary)
                    .env("LD_LIBRARY_PATH", &lib)
                    .env("QEMU_MODULE_DIR", &modules),
            )?;
            if listing.contains("not found") {
                return Err("Не найдены зависимости QEMU".into());
            }
            for line in listing.lines() {
                if let Some((_, after)) = line.split_once("=>") {
                    if let Some(name) = after.split_whitespace().next() {
                        let p = Path::new(name);
                        if p.parent() == Some(lib.as_path()) {
                            keep.insert(p.to_owned());
                        }
                    }
                }
            }
        }
        for entry in fs::read_dir(&lib)? {
            let path = entry?.path();
            if path.is_file() && !keep.contains(&path) {
                fs::remove_file(path)?;
            }
        }
        for name in ["qemu-system-x86_64", "qemu-img"] {
            checked(
                Command::new(minimal.join("usr/local/bin").join(name))
                    .arg("--version")
                    .env("LD_LIBRARY_PATH", &lib)
                    .env("QEMU_MODULE_DIR", &modules),
            )?;
        }
        atomic(
            &minimal.join(".complete"),
            b"FreeBSD:14:amd64 qemu-nox11\n",
            0o600,
        )?;
        fs::rename(minimal, &target)?;
        Ok(())
    })();
    let _ = fs::remove_dir_all(&work);
    result
}

fn guest(base: &Path, disk_gib: u64) -> Result<()> {
    let vm = base.join("vm");
    fs::create_dir_all(&vm)?;
    let disk = vm.join("docker.qcow2");
    if !disk.exists() {
        let image = vm.join(format!(".alpine-download-{}", std::process::id()));
        download(IMAGE, &image, 2 * 1024 * 1024 * 1024)?;
        if digest(&image, "sha512")? != IMAGE_SHA {
            fs::remove_file(image)?;
            return Err("SHA-512 Alpine не совпадает".into());
        }
        checked(
            Command::new(base.join("qemu/usr/local/bin/qemu-img"))
                .arg("resize")
                .arg(&image)
                .arg(format!("{disk_gib}G"))
                .env("LD_LIBRARY_PATH", base.join("qemu/usr/local/lib")),
        )?;
        fs::rename(image, disk)?;
    }
    let key = vm.join("guest-key");
    if !key.exists() {
        checked(
            Command::new("ssh-keygen")
                .args(["-q", "-t", "ed25519", "-N", "", "-f"])
                .arg(&key),
        )?;
    }
    fs::set_permissions(&key, fs::Permissions::from_mode(0o600))?;
    let seed = vm.join("seed");
    fs::create_dir_all(&seed)?;
    if !seed.join("meta-data").exists() {
        atomic(
            &seed.join("meta-data"),
            format!(
                "instance-id: hc-{}-{}\nlocal-hostname: helios-container\n",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_nanos()
            )
            .as_bytes(),
            0o600,
        )?;
    }
    if !vm.join("seed.iso").exists() {
        let public = fs::read_to_string(vm.join("guest-key.pub"))?;
        if !public.starts_with("ssh-ed25519 ") || public.trim().contains('\n') {
            return Err("Некорректный SSH-ключ".into());
        }
        let data = format!(
            r#"#cloud-config
hostname: helios-container
disable_root: false
ssh_pwauth: false
users:
  - name: root
    lock_passwd: false
    hashed_passwd: '*'
    ssh_authorized_keys:
      - {}
write_files:
  - path: /etc/apk/repositories
    content: |
      https://dl-cdn.alpinelinux.org/alpine/v3.24/main
      https://dl-cdn.alpinelinux.org/alpine/v3.24/community
  - path: /etc/docker/daemon.json
    content: |
      {{"log-driver":"local","log-opts":{{"max-size":"10m","max-file":"3"}}}}
  - path: /root/install-docker.sh
    permissions: '0700'
    content: |
      #!/bin/sh
      set -eu
      apk update
      apk add docker docker-cli-compose openssh-client util-linux-misc
      mkdir -p /workspace
      rc-update add cgroups boot
      rc-service cgroups start
      rc-update add docker default
      rc-service docker start
      for i in $(seq 1 90); do
        if docker info >/dev/null 2>&1; then
          touch /root/docker-ready
          exit 0
        fi
        sleep 2
      done
      exit 1
runcmd:
  - [sh, -c, '/root/install-docker.sh > /root/install-docker.log 2>&1']
"#,
            public.trim()
        );
        atomic(&seed.join("user-data"), data.as_bytes(), 0o600)?;
        let temporary = vm.join(format!(".seed-{}.iso", std::process::id()));
        checked(
            Command::new("makefs")
                .args(["-t", "cd9660", "-o", "rockridge,label=cidata"])
                .arg(&temporary)
                .arg(seed),
        )?;
        fs::rename(temporary, vm.join("seed.iso"))?;
    }
    Ok(())
}

pub(super) fn launchers(base: &Path) -> Result<()> {
    let bin = PathBuf::from(env::var("HOME")?).join(".local/bin");
    no_links(&bin)?;
    fs::create_dir_all(&bin)?;
    for (name, args) in [("helios-container", ""), ("docker", " docker")] {
        let target = bin.join(name);
        no_links(&target)?;
        if target.exists()
            && !fs::read_to_string(&target)?.contains("# helios-container managed launcher")
        {
            return Err(format!("{} не принадлежит kit", target.display()).into());
        }
        atomic(
            &target,
            format!(
                "#!/bin/sh\n# helios-container managed launcher\nexec {} --base {}{} \"$@\"\n",
                quote(&base.join("helios-container-native").to_string_lossy()),
                quote(&base.to_string_lossy()),
                args
            )
            .as_bytes(),
            0o700,
        )?;
    }
    Ok(())
}

pub(super) fn run(args: &[String]) -> Result<()> {
    let home = PathBuf::from(env::var("HOME")?);
    let mut base = home.join(".local/helios-container");
    let (mut memory, mut cpus, mut disk) = (1024u64, 1u64, 12u64);
    let (mut no_profile, mut no_launchers) = (false, false);
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--no-profile" => no_profile = true,
            "--no-launchers" => no_launchers = true,
            "--prefix" | "--memory" | "--cpus" | "--disk" => {
                let name = &args[i];
                i += 1;
                let value = args.get(i).ok_or("Нет значения параметра установки")?;
                match name.as_str() {
                    "--prefix" => {
                        base = if value == "~" {
                            home.clone()
                        } else if let Some(rest) = value.strip_prefix("~/") {
                            home.join(rest)
                        } else {
                            PathBuf::from(value)
                        }
                    }
                    "--memory" => memory = value.parse()?,
                    "--cpus" => cpus = value.parse()?,
                    _ => disk = value.parse()?,
                }
            }
            "--help" => {
                println!("install [--prefix PATH] [--memory 1024] [--cpus 1] [--disk 12] [--no-profile] [--no-launchers]");
                return Ok(());
            }
            _ => return Err("Неизвестный параметр установки".into()),
        }
        i += 1;
    }
    if unsafe { libc::geteuid() } == 0 {
        return Err("Запустите установщик без root и sudo".into());
    }
    if output(Command::new("uname").arg("-s"))?.trim() != "FreeBSD"
        || output(Command::new("uname").arg("-m"))?.trim() != "amd64"
        || !output(Command::new("uname").arg("-r"))?.starts_with("14.")
    {
        return Err("Поддерживается FreeBSD 14.x amd64".into());
    }
    if !(512..=16384).contains(&memory) || !(1..=8).contains(&cpus) || !(4..=64).contains(&disk) {
        return Err("RAM 512–16384 МиБ, CPU 1–8, диск 4–64 ГиБ".into());
    }
    let base = safe_base(&base)?;
    for tool in [
        "pkg",
        "curl",
        "tar",
        "makefs",
        "ssh",
        "scp",
        "ssh-keygen",
        "ldd",
        "sha512",
        "sha256",
    ] {
        checked(
            Command::new("sh").args(["-c", &format!("command -v {} >/dev/null", quote(tool))]),
        )?;
    }
    if !Path::new("/usr/share/keys/pkg/trusted").is_dir() {
        return Err("Не найдены ключи подписей pkg".into());
    }
    unsafe {
        libc::umask(0o077);
    }
    fs::create_dir_all(&base)?;
    fs::set_permissions(&base, fs::Permissions::from_mode(0o700))?;
    fs::create_dir_all(base.join("vm"))?;
    for name in [
        "config.json",
        "VERSION",
        "vm/docker.qcow2",
        "vm/guest-key",
        "vm/guest-key.pub",
        "vm/seed",
        "vm/seed.iso",
        "qemu",
        "helios-container-native",
        ".update.lock",
    ] {
        no_links(&base.join(name))?;
    }
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .mode(0o600)
        .open(base.join(".update.lock"))?;
    use std::os::fd::AsRawFd;
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    if !base.join("config.json").exists() {
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let port = listener.local_addr()?.port();
        atomic(
            &base.join("config.json"),
            format!(
                "{}\n",
                serde_json::to_string_pretty(
                    &json!({"memory_mib": memory, "cpus": cpus, "ssh_port": port, "forwards": []})
                )?
            )
            .as_bytes(),
            0o600,
        )?;
    }
    let kit = Kit::load(base.clone())?;
    if kit.pid().is_none() {
        if !base.join("qemu/.complete").exists() {
            let text = output(Command::new("df").args(["-kP"]).arg(&base))?;
            let available: u64 = text
                .lines()
                .last()
                .and_then(|s| s.split_whitespace().nth(3))
                .ok_or("Не удалось определить свободное место")?
                .parse()?;
            if available < 2 * 1024 * 1024 {
                return Err("Для установки требуется 2 ГиБ свободного места".into());
            }
        }
        qemu(&base)?;
        guest(&base, disk)?;
    }
    let executable = env::current_exe()?.canonicalize()?;
    let destination = base.join("helios-container-native");
    let version_source = executable
        .parent()
        .ok_or("Нет каталога бинарника")?
        .join("VERSION");
    let marker = if version_source.exists() {
        let marker = fs::read_to_string(version_source)?;
        if marker.trim().trim_start_matches('v') != env!("CARGO_PKG_VERSION") {
            return Err("VERSION не совпадает с версией сборки".into());
        }
        Some(marker)
    } else {
        None
    };
    if !destination.exists() || executable != destination.canonicalize()? {
        atomic(&destination, &fs::read(&executable)?, 0o700)?;
    }
    if let Some(marker) = marker {
        atomic(&base.join("VERSION"), marker.as_bytes(), 0o600)?;
    }
    if !no_launchers {
        launchers(&base)?;
    }
    if !no_profile {
        super::profile(&base)?;
    }
    drop(lock);
    kit.start(true)?;
    println!("Готово. Выполните: . ~/.profile\nЗатем: docker run --rm hello-world");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn package_paths_stay_in_local_prefix() {
        for name in [
            "+MANIFEST",
            "usr/local/bin/qemu-img",
            "/usr/local/bin/qemu-img",
        ] {
            assert!(package_path_allowed(name), "{name}");
        }
        for name in [
            "../outside",
            "/usr/local/../etc/passwd",
            "/etc/passwd",
            "/usr/local-other/bin/tool",
        ] {
            assert!(!package_path_allowed(name), "{name}");
        }
    }
    #[test]
    fn parent_traversal_rejected() {
        assert!(no_links(Path::new("/tmp/../tmp/kit")).is_err());
    }
    #[test]
    fn insecure_download_rejected() {
        assert!(download("http://example.invalid", Path::new("/tmp/unused"), 1).is_err());
    }
}
