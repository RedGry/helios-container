//! Native runtime, using the existing VM and on-disk JSON contracts.
mod agent;
mod dashboard;
mod idle;
mod install;
mod update;
use serde_json::{json, Value};
use std::{
    env, fs,
    io::{self, BufRead, BufReader, IsTerminal, Read, Write},
    net::TcpListener,
    os::unix::{
        fs::{OpenOptionsExt, PermissionsExt},
        net::UnixStream,
    },
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const BEGIN: &str = "# >>> helios-container >>>";
const END: &str = "# <<< helios-container <<<";

fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}
fn shell(args: &[String]) -> String {
    args.iter().map(|s| quote(s)).collect::<Vec<_>>().join(" ")
}
fn checked(cmd: &mut Command) -> Result<()> {
    let status = cmd.status()?;
    if !status.success() {
        return Err(format!("Команда завершилась с кодом {}", status.code().unwrap_or(1)).into());
    }
    Ok(())
}
fn output(cmd: &mut Command) -> Result<String> {
    let out = cmd.output()?;
    if !out.status.success() {
        return Err("Команда не выполнена".into());
    }
    Ok(String::from_utf8(out.stdout)?)
}
fn short_output(cmd: &mut Command, timeout: Duration) -> Result<String> {
    let mut child = cmd.stdout(Stdio::piped()).stderr(Stdio::null()).spawn()?;
    let mut pipe = child.stdout.take().ok_or("Нет stdout")?;
    let reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 8192];
        let mut exceeded = false;
        loop {
            let n = pipe.read(&mut chunk)?;
            if n == 0 {
                break;
            }
            if bytes.len() + n <= 262144 {
                bytes.extend_from_slice(&chunk[..n]);
            } else {
                exceeded = true;
            }
        }
        Ok::<_, io::Error>((bytes, exceeded))
    });
    let until = Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait()? {
            let (bytes, exceeded) = reader.join().map_err(|_| "Ошибка чтения команды")??;
            if !status.success() || exceeded {
                return Err("Команда не выполнена или ответ слишком велик".into());
            }
            return Ok(String::from_utf8(bytes)?);
        }
        if Instant::now() >= until {
            let _ = child.kill();
            let _ = child.wait();
            return Err("Таймаут команды".into());
        }
        thread::sleep(Duration::from_millis(50));
    }
}

static TEMP_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
fn atomic(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let tmp = path.with_extension(format!(
        "tmp-{}-{}",
        std::process::id(),
        TEMP_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .open(&tmp)?;
    if let Err(error) = (|| -> io::Result<()> {
        file.write_all(bytes)?;
        file.set_permissions(fs::Permissions::from_mode(mode))?;
        file.sync_all()?;
        fs::rename(&tmp, path)?;
        Ok(())
    })() {
        let _ = fs::remove_file(&tmp);
        return Err(error.into());
    }
    Ok(())
}
fn read_json(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}
fn validate(c: &Value) -> Result<()> {
    for (key, low, high) in [
        ("memory_mib", 512, 16384),
        ("cpus", 1, 4),
        ("ssh_port", 1024, 65535),
    ] {
        let n = c[key].as_u64().ok_or("Некорректные настройки VM")?;
        if !(low..=high).contains(&n) {
            return Err("RAM 512–16384 МиБ, CPU 1–4, SSH-порт 1024–65535".into());
        }
    }
    if c.get("auto_stop").is_some_and(|v| !v.is_boolean()) {
        return Err("auto_stop должен быть true или false".into());
    }
    if let Some(forwards) = c.get("forwards") {
        for item in forwards.as_array().ok_or("forwards должен быть массивом")? {
            if !(1..=65535).contains(&item["guest"].as_u64().unwrap_or(0))
                || !(1024..=65535).contains(&item["host"].as_u64().unwrap_or(0))
            {
                return Err("Некорректный проброс порта".into());
            }
        }
    }
    Ok(())
}

struct Lease(fs::File, PathBuf);
impl Lease {
    fn acquire(base: &Path) -> Result<Self> {
        let path = base.join("vm/activity.lock");
        let file = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(path)?;
        use std::os::fd::AsRawFd;
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_SH) } != 0 {
            return Err(io::Error::last_os_error().into());
        }
        let marker = base.join("vm/activity");
        touch(&marker)?;
        Ok(Self(file, marker))
    }
}
impl Drop for Lease {
    fn drop(&mut self) {
        let _ = touch(&self.1);
        use std::os::fd::AsRawFd;
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}
fn touch(path: &Path) -> Result<()> {
    let file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    file.set_modified(std::time::SystemTime::now())?;
    Ok(())
}

struct Kit {
    base: PathBuf,
    c: Value,
}
impl Kit {
    fn load(base: PathBuf) -> Result<Self> {
        let c = read_json(&base.join("config.json"))?;
        validate(&c)?;
        Ok(Self { base, c })
    }
    fn vm(&self) -> PathBuf {
        self.base.join("vm")
    }
    fn save(&self) -> Result<()> {
        validate(&self.c)?;
        atomic(
            &self.base.join("config.json"),
            format!("{}\n", serde_json::to_string_pretty(&self.c)?).as_bytes(),
            0o600,
        )
    }
    fn pid(&self) -> Option<u32> {
        let pid: u32 = fs::read_to_string(self.vm().join("qemu.pid"))
            .ok()?
            .trim()
            .parse()
            .ok()?;
        let listing = output(Command::new("ps").args([
            "-ww",
            "-p",
            &pid.to_string(),
            "-o",
            "uid=",
            "-o",
            "command=",
        ]))
        .ok()?;
        let (uid, command) = listing.trim().split_once(char::is_whitespace)?;
        if uid.parse::<u32>().ok()? == unsafe { libc::getuid() }
            && command.contains("qemu-system-x86_64")
            && command.contains(self.vm().join("docker.qcow2").to_str()?)
        {
            Some(pid)
        } else {
            None
        }
    }
    fn ssh_options(&self, scp: bool) -> Vec<String> {
        vec![
            if scp { "-P" } else { "-p" }.into(),
            self.c["ssh_port"].to_string(),
            "-i".into(),
            self.vm().join("guest-key").display().to_string(),
            "-o".into(),
            "IdentitiesOnly=yes".into(),
            "-o".into(),
            "BatchMode=yes".into(),
            "-o".into(),
            "StrictHostKeyChecking=accept-new".into(),
            "-o".into(),
            format!(
                "UserKnownHostsFile={}",
                self.vm().join("known_hosts").display()
            ),
            "-o".into(),
            "ConnectTimeout=10".into(),
        ]
    }
    fn ssh(&self, command: &str, tty: bool) -> Command {
        let mut cmd = Command::new("ssh");
        if tty {
            cmd.arg("-t");
        }
        cmd.args(self.ssh_options(false))
            .arg("root@127.0.0.1")
            .arg(command);
        cmd
    }
    fn qmp(&self, command: &str, args: Value) -> Result<Value> {
        if self.pid().is_none() {
            return Err("VM остановлена".into());
        }
        let stream = UnixStream::connect(self.vm().join("qmp.sock"))?;
        stream.set_read_timeout(Some(Duration::from_secs(10)))?;
        stream.set_write_timeout(Some(Duration::from_secs(10)))?;
        let mut reader = BufReader::new(stream);
        let mut line = String::new();
        reader.read_line(&mut line)?;
        for request in [
            json!({"execute":"qmp_capabilities"}),
            json!({"execute":command,"arguments":args}),
        ] {
            writeln!(reader.get_mut(), "{}", request)?;
            loop {
                line.clear();
                if reader.read_line(&mut line)? == 0 {
                    return Err("QMP закрыл соединение".into());
                }
                let reply: Value = serde_json::from_str(&line)?;
                if reply.get("error").is_some() {
                    return Err("QMP отклонил операцию".into());
                }
                if let Some(value) = reply.get("return") {
                    if command == request["execute"].as_str().unwrap_or("") {
                        return Ok(value.clone());
                    }
                    break;
                }
            }
        }
        Err("Нет ответа QMP".into())
    }
    fn start(&self, wait: bool) -> Result<()> {
        let update_lock = FileLock::exclusive(&self.base.join(".update.lock"))?;
        let lifecycle_lock = FileLock::exclusive(&self.base.join(".lifecycle.lock"))?;
        let current = Self::load(self.base.clone())?;
        if current.c != self.c {
            return current.start_locked(wait, update_lock, lifecycle_lock);
        }
        self.start_locked(wait, update_lock, lifecycle_lock)
    }
    fn start_locked(
        &self,
        wait: bool,
        update_lock: FileLock,
        lifecycle_lock: FileLock,
    ) -> Result<()> {
        if self.pid().is_none() {
            let vm = self.vm();
            let qemu = self.base.join("qemu/usr/local");
            let mut net = format!(
                "user,id=net0,hostfwd=tcp:127.0.0.1:{}-:22",
                self.c["ssh_port"]
            );
            if let Some(maps) = self.c["forwards"].as_array() {
                for m in maps {
                    net += &format!(",hostfwd=tcp:127.0.0.1:{}-:{}", m["host"], m["guest"]);
                }
            }
            checked(
                Command::new(qemu.join("bin/qemu-system-x86_64"))
                    .env("LD_LIBRARY_PATH", qemu.join("lib"))
                    .env("QEMU_MODULE_DIR", qemu.join("lib/qemu"))
                    .args([
                        "-L",
                        &qemu.join("share/qemu").display().to_string(),
                        "-machine",
                        "q35",
                        "-accel",
                        "tcg",
                        "-cpu",
                        "max",
                        "-smp",
                        &self.c["cpus"].to_string(),
                        "-m",
                        &self.c["memory_mib"].to_string(),
                        "-drive",
                        &format!(
                            "file={},format=qcow2,if=virtio,discard=unmap",
                            vm.join("docker.qcow2").display()
                        ),
                        "-drive",
                        &format!(
                            "file={},format=raw,media=cdrom,readonly=on",
                            vm.join("seed.iso").display()
                        ),
                        "-netdev",
                        &net,
                        "-device",
                        "virtio-net-pci,netdev=net0,romfile=",
                        "-display",
                        "none",
                        "-monitor",
                        "none",
                        "-serial",
                        &format!("file:{}", vm.join("console.log").display()),
                        "-qmp",
                        &format!("unix:{},server=on,wait=off", vm.join("qmp.sock").display()),
                        "-pidfile",
                        &vm.join("qemu.pid").display().to_string(),
                        "-daemonize",
                    ])
                    .stdin(Stdio::null()),
            )?;
            eprintln!(
                "VM запущена: {} CPU, {} МиБ RAM",
                self.c["cpus"], self.c["memory_mib"]
            );
        }
        drop(lifecycle_lock);
        drop(update_lock);
        if wait {
            self.ready()?;
        }
        self.ensure_services()?;
        Ok(())
    }
    fn ready(&self) -> Result<()> {
        let pid = self.pid().ok_or("VM завершилась")?.to_string();
        let marker = self.vm().join("ready.pid");
        if fs::read_to_string(&marker).unwrap_or_default().trim() == pid {
            return Ok(());
        }
        let until = Instant::now() + Duration::from_secs(600);
        eprintln!("Ожидаю Linux и Docker…");
        while Instant::now() < until {
            if self.pid().is_none() {
                return Err("VM завершилась. Проверьте helios-container logs".into());
            }
            if short_output(
                self.ssh("docker info --format '{{.ServerVersion}}'", false)
                    .stdin(Stdio::null()),
                Duration::from_secs(20),
            )
            .is_ok()
            {
                atomic(&marker, pid.as_bytes(), 0o600)?;
                return Ok(());
            }
            thread::sleep(Duration::from_secs(5));
        }
        Err("Docker не готов за 10 минут".into())
    }
    fn stop(&self, force: bool) -> Result<()> {
        let _lock = FileLock::exclusive(&self.base.join(".lifecycle.lock"))?;
        if self.pid().is_none() {
            println!("VM остановлена");
            return Ok(());
        }
        self.qmp(if force { "quit" } else { "system_powerdown" }, json!({}))?;
        let until = Instant::now() + Duration::from_secs(120);
        while Instant::now() < until && self.pid().is_some() {
            thread::sleep(Duration::from_secs(1));
        }
        if self.pid().is_some() {
            return Err("Выключение ещё не завершилось. Проверьте status".into());
        }
        println!("VM остановлена");
        Ok(())
    }
    fn ensure_services(&self) -> Result<()> {
        idle::ensure(self)?;
        if self.base.join("web.json").exists() {
            agent::ensure(&self.base)?;
        }
        Ok(())
    }
    fn forward(&mut self, guest: u16, preferred: u16) -> Result<u16> {
        let _lease = Lease::acquire(&self.base)?;
        self.start(true)?;
        let _lock = FileLock::exclusive(&self.base.join(".lifecycle.lock"))?;
        self.c = read_json(&self.base.join("config.json"))?;
        if let Some(old) = self.c["forwards"]
            .as_array()
            .and_then(|m| m.iter().find(|m| m["guest"] == guest))
        {
            return Ok(old["host"].as_u64().ok_or("Некорректный порт")? as u16);
        }
        let listener = TcpListener::bind(("127.0.0.1", preferred))?;
        let host = listener.local_addr()?.port();
        drop(listener);
        let reply = self.qmp(
            "human-monitor-command",
            json!({"command-line":format!("hostfwd_add net0 tcp:127.0.0.1:{host}-:{guest}")}),
        )?;
        if !reply.as_str().unwrap_or("error").trim().is_empty() {
            return Err("QEMU не создал проброс порта".into());
        }
        if self.c.get("forwards").is_none() {
            self.c["forwards"] = json!([]);
        }
        self.c["forwards"]
            .as_array_mut()
            .ok_or("Некорректные forwards")?
            .push(json!({"host":host,"guest":guest}));
        if let Err(error) = self.save() {
            let _ = self.qmp(
                "human-monitor-command",
                json!({"command-line":format!("hostfwd_remove net0 tcp:127.0.0.1:{host}")}),
            );
            return Err(error);
        }
        Ok(host)
    }
}
struct FileLock(fs::File);
impl FileLock {
    fn exclusive(path: &Path) -> Result<Self> {
        use std::os::fd::AsRawFd;
        let file = fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(path)?;
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) } != 0 {
            return Err(io::Error::last_os_error().into());
        }
        Ok(Self(file))
    }
}
impl Drop for FileLock {
    fn drop(&mut self) {
        use std::os::fd::AsRawFd;
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}
fn port(value: &str, low: u16) -> Result<u16> {
    let n = value.parse::<u16>()?;
    if n < low {
        Err("Некорректный порт".into())
    } else {
        Ok(n)
    }
}
fn profile(base: &Path) -> Result<()> {
    let home = PathBuf::from(env::var("HOME")?);
    let path = home.join(".profile");
    if fs::symlink_metadata(&path).is_ok_and(|m| m.file_type().is_symlink()) {
        return Err(".profile не должен быть ссылкой".into());
    }
    let original = fs::read_to_string(&path).unwrap_or_default();
    let mut content = original.clone();
    match (content.find(BEGIN), content.find(END)) {
        (Some(a), Some(b)) if b >= a => {
            let mut end = b + END.len();
            if content[end..].starts_with("\r\n") {
                end += 2;
            } else if content[end..].starts_with('\n') {
                end += 1;
            }
            content.replace_range(a..end, "");
        }
        (None, None) => {}
        _ => return Err("Повреждён блок helios-container в .profile".into()),
    }
    if !base.join("profile.before").exists() {
        atomic(&base.join("profile.before"), original.as_bytes(), 0o600)?;
    }
    if !content.is_empty() && !content.ends_with('\n') {
        content.push('\n');
    }
    content += &format!("{BEGIN}\nexport PATH=\"$HOME/.local/bin:$PATH\"\n{END}\n");
    atomic(&path, content.as_bytes(), 0o600)?;
    println!("PATH настроен. Выполните: . ~/.profile");
    Ok(())
}
fn uninstall(kit: &Kit, args: &[String]) -> Result<()> {
    if args != ["--yes"] {
        return Err("uninstall --yes удалит VM, контейнеры, volumes и настройки без возможности восстановления. Сначала выполните stop".into());
    }
    let base = install::safe_base(&kit.base)?;
    let _update = FileLock::exclusive(&base.join(".update.lock"))?;
    let _lifecycle = FileLock::exclusive(&base.join(".lifecycle.lock"))?;
    if kit.pid().is_some() {
        return Err("Сначала выполните helios-container stop".into());
    }
    idle::stop(&base)?;
    if base.join("web.json").exists() {
        agent::manage(kit, &["remove".into()])?;
    }
    let home = PathBuf::from(env::var("HOME")?);
    for name in ["helios-container", "docker"] {
        let path = home.join(".local/bin").join(name);
        install::no_links(&path)?;
        if path.exists() {
            let text = fs::read_to_string(&path)?;
            if text.contains("# helios-container managed launcher")
                && text.contains(&base.to_string_lossy().to_string())
            {
                fs::remove_file(path)?;
            }
        }
    }
    let path = home.join(".profile");
    install::no_links(&path)?;
    if path.exists() {
        let mut text = fs::read_to_string(&path)?;
        if let (Some(a), Some(b)) = (text.find(BEGIN), text.find(END)) {
            if b >= a {
                text.replace_range(a..b + END.len(), "");
                atomic(&path, text.as_bytes(), 0o600)?;
            }
        }
    }
    fs::remove_dir_all(&base)?;
    println!("Kit и данные VM удалены");
    Ok(())
}
fn main_inner() -> Result<i32> {
    let mut args: Vec<String> = env::args().skip(1).collect();
    let mut base = PathBuf::from(env::var("HOME")?).join(".local/helios-container");
    if args.first().is_some_and(|v| v == "--base") {
        if args.len() < 3 {
            return Err("Нужны каталог и команда".into());
        }
        base = PathBuf::from(args.remove(1));
        args.remove(0);
    }
    if args.is_empty() || ["--help", "-h", "help"].contains(&args[0].as_str()) {
        println!("helios-container (Rust)\nstart, stop [--force], status, docker …, ssh …, upload, download, forward, configure, logs, profile, version\ninstall, web, update, check-update, uninstall: нативные команды\n--base PATH: существующий каталог kit");
        return Ok(0);
    }
    if args[0] == "--build-version" {
        println!("{}", env!("CARGO_PKG_VERSION"));
        return Ok(0);
    }
    if args[0] == "version" {
        let v = fs::read_to_string(base.join("VERSION")).unwrap_or_else(|_| "dev".into());
        println!(
            "helios-container {} (Rust {})",
            v.trim(),
            env!("CARGO_PKG_VERSION")
        );
        return Ok(0);
    }
    if args[0] == "install" {
        install::run(&args[1..])?;
        return Ok(0);
    }
    let base = base.canonicalize()?;
    let mut kit = Kit::load(base)?;
    match args[0].as_str() {
        "_agent" => agent::serve(kit.base.clone())?,
        "_idle" => idle::run(kit.base.clone())?,

        "start" => {
            let _lease = Lease::acquire(&kit.base)?;
            kit.start(true)?;
        }
        "stop" => {
            if args.len() > 2 || args.get(1).is_some_and(|v| v != "--force") {
                return Err("stop [--force]".into());
            }
            kit.stop(args.len() == 2)?;
        }
        "status" => {
            println!(
                "{}, {} CPU, {} МиБ RAM, SSH 127.0.0.1:{}",
                if kit.pid().is_some() {
                    "Работает"
                } else {
                    "Остановлена"
                },
                kit.c["cpus"],
                kit.c["memory_mib"],
                kit.c["ssh_port"]
            );
            if let Some(pid) = kit.pid() {
                checked(Command::new("ps").args([
                    "-p",
                    &pid.to_string(),
                    "-o",
                    "pid,rss,%cpu,etime,comm",
                ]))?;
            }
            if let Some(m) = kit.c["forwards"].as_array() {
                for f in m {
                    println!("TCP 127.0.0.1:{} → VM:{}", f["host"], f["guest"]);
                }
            }
        }
        "docker" | "ssh" => {
            let _lease = Lease::acquire(&kit.base)?;
            kit.start(true)?;
            let command = if args[0] == "docker" {
                shell(&args)
            } else if args.len() == 2 {
                args[1].clone()
            } else {
                shell(&args[1..])
            };
            let tty = io::stdin().is_terminal()
                && (args[0] == "ssh"
                    || args.iter().any(|v| {
                        ["-it", "-ti", "-t", "--tty", "--tty=true"].contains(&v.as_str())
                    }));
            return Ok(kit.ssh(&command, tty).status()?.code().unwrap_or(1));
        }
        "logs" => {
            let path = kit.vm().join("console.log");
            if path.exists() {
                checked(Command::new("tail").arg("-n").arg("60").arg(path))?;
            }
        }
        "profile" => profile(&kit.base)?,
        "forward" => {
            if !(2..=3).contains(&args.len()) {
                return Err("forward GUEST [HOST]".into());
            }
            let guest = port(&args[1], 1)?;
            let preferred = if args.len() == 3 {
                port(&args[2], 1024)?
            } else {
                0
            };
            let host = kit.forward(guest, preferred)?;
            println!("TCP 127.0.0.1:{host} → VM:{guest}");
        }
        "configure" => {
            let _lock = FileLock::exclusive(&kit.base.join(".lifecycle.lock"))?;
            kit.c = read_json(&kit.base.join("config.json"))?;
            if !(args.len() - 1).is_multiple_of(2) {
                return Err("configure требует пары --параметр значение".into());
            }
            for pair in args[1..].chunks(2) {
                let key = match pair[0].as_str() {
                    "--memory" => "memory_mib",
                    "--cpus" => "cpus",
                    "--ssh-port" => "ssh_port",
                    "--auto-stop" => "auto_stop",
                    _ => return Err("Неизвестный параметр".into()),
                };
                if key != "auto_stop" && kit.pid().is_some() {
                    return Err("Сначала выполните helios-container stop".into());
                }
                kit.c[key] = if key == "auto_stop" {
                    match pair[1].as_str() {
                        "on" => json!(true),
                        "off" => json!(false),
                        _ => return Err("auto-stop: on или off".into()),
                    }
                } else {
                    json!(pair[1].parse::<u64>()?)
                };
            }
            kit.save()?;
            if kit.pid().is_some() {
                kit.ensure_services()?;
            }
            println!("Настройки сохранены");
        }
        "upload" | "download" => {
            if !(2..=3).contains(&args.len()) {
                return Err("upload/download SOURCE [DESTINATION]".into());
            }
            let upload = args[0] == "upload";
            let source = &args[1];
            let destination =
                args.get(2)
                    .map(String::as_str)
                    .unwrap_or(if upload { "/workspace" } else { "." });
            let remote = if upload { destination } else { source };
            if !remote.starts_with('/') {
                return Err("Путь внутри VM должен быть абсолютным".into());
            }
            let _lease = Lease::acquire(&kit.base)?;
            kit.start(true)?;
            let src = if upload {
                source.clone()
            } else {
                format!("root@127.0.0.1:{source}")
            };
            let dst = if upload {
                format!("root@127.0.0.1:{destination}")
            } else {
                destination.into()
            };
            return Ok(Command::new("scp")
                .arg("-r")
                .args(kit.ssh_options(true))
                .arg("--")
                .arg(src)
                .arg(dst)
                .status()?
                .code()
                .unwrap_or(1));
        }
        "web" => agent::manage(&kit, &args[1..])?,
        "update" | "check-update" => update::run(&kit, &args)?,
        "uninstall" => uninstall(&kit, &args[1..])?,
        _ => return Err("Неизвестная команда. Выполните helios-container --help".into()),
    }
    Ok(0)
}
fn main() {
    unsafe {
        libc::umask(0o077);
    }
    match main_inner() {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("helios-container: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_command_drains_more_than_pipe_capacity() {
        let raw = short_output(
            Command::new("sh").args(["-c", "head -c 200000 /dev/zero"]),
            Duration::from_secs(3),
        )
        .unwrap();
        assert_eq!(raw.len(), 200000);
    }
    #[test]
    fn quoted_arguments_cannot_become_shell_code() {
        assert_eq!(
            shell(&["docker".into(), "x'; touch /tmp/bad; '".into()]),
            "'docker' 'x'\"'\"'; touch /tmp/bad; '\"'\"''"
        );
    }
    #[test]
    fn validate_limits_and_unknown_values() {
        let mut c = json!({"memory_mib":4096,"cpus":4,"ssh_port":40328,"forwards":[],"future":{"keep":true}});
        assert!(validate(&c).is_ok());
        c["cpus"] = json!(5);
        assert!(validate(&c).is_err());
        c["cpus"] = json!(true);
        assert!(validate(&c).is_err());
    }
    #[test]
    fn ports_reject_zero_and_flags() {
        assert!(port("0", 1).is_err());
        assert!(port("--all", 1).is_err());
        assert!(port("65536", 1).is_err());
        assert_eq!(port("8080", 1).unwrap(), 8080);
    }
}
