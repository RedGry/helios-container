//! Conservative user-owned idle shutdown. Observation failure never means inactivity.
use super::*;
use std::os::{fd::AsRawFd, unix::process::CommandExt};

const IDLE_SECONDS: u64 = 1800;
const POLL_SECONDS: u64 = 60;
const CHAIN: &str = "HC_IDLE";

fn enabled(kit: &Kit) -> bool {
    kit.c["auto_stop"].as_bool().unwrap_or(true)
}
fn owned_pid(base: &Path) -> Option<u32> {
    let pid: u32 = fs::read_to_string(base.join("vm/idle.pid"))
        .ok()?
        .trim()
        .parse()
        .ok()?;
    let text = output(Command::new("ps").args([
        "-ww",
        "-p",
        &pid.to_string(),
        "-o",
        "uid=",
        "-o",
        "command=",
    ]))
    .ok()?;
    let (uid, command) = text.trim().split_once(char::is_whitespace)?;
    if uid.parse::<u32>().ok()? != unsafe { libc::getuid() } {
        return None;
    }
    let exe = base.join("helios-container-native");
    if command.contains(base.to_str()?)
        && ((command.contains(exe.to_str()?)
            && command.split_whitespace().any(|part| part == "_idle"))
            || command.contains(base.join("idle.py").to_str()?))
    {
        Some(pid)
    } else {
        None
    }
}
pub(super) fn ensure(kit: &Kit) -> Result<()> {
    if let Some(pid) = owned_pid(&kit.base) {
        let command =
            output(Command::new("ps").args(["-ww", "-p", &pid.to_string(), "-o", "command="]))?;
        if command.contains(&kit.base.join("idle.py").display().to_string()) {
            stop(&kit.base)?;
        } else {
            return Ok(());
        }
    }
    if !enabled(kit) {
        return Ok(());
    }
    for name in ["idle.pid", "idle.lock", "idle.log"] {
        super::install::no_links(&kit.vm().join(name))?;
    }
    let log = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(kit.vm().join("idle.log"))?;
    let mut cmd = Command::new(kit.base.join("helios-container-native"));
    cmd.arg("--base")
        .arg(&kit.base)
        .arg("_idle")
        .stdin(Stdio::null())
        .stdout(log.try_clone()?)
        .stderr(log);
    unsafe {
        cmd.pre_exec(|| {
            if libc::setsid() < 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
    cmd.spawn()?;
    Ok(())
}
pub(super) fn stop(base: &Path) -> Result<()> {
    if let Some(pid) = owned_pid(base) {
        if unsafe { libc::kill(pid as i32, libc::SIGTERM) } != 0 {
            return Err(io::Error::last_os_error().into());
        }
        for _ in 0..50 {
            if owned_pid(base).is_none() {
                let _ = fs::remove_file(base.join("vm/idle.pid"));
                return Ok(());
            }
            thread::sleep(Duration::from_millis(100));
        }
        return Err("Монитор ещё останавливается".into());
    }
    Ok(())
}
struct Lock(fs::File);
impl Lock {
    fn try_exclusive(path: &Path) -> Result<Option<Self>> {
        super::install::no_links(path)?;
        let file = fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(path)?;
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
            return Ok(Some(Self(file)));
        }
        let err = io::Error::last_os_error();
        if err.kind() == io::ErrorKind::WouldBlock {
            Ok(None)
        } else {
            Err(err.into())
        }
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}
struct PidMarker(PathBuf);
impl Drop for PidMarker {
    fn drop(&mut self) {
        if fs::read_to_string(&self.0).is_ok_and(|s| s.trim() == std::process::id().to_string()) {
            let _ = fs::remove_file(&self.0);
        }
    }
}

fn ports(kit: &Kit) -> Result<Vec<u16>> {
    let mut ports = Vec::new();
    if let Some(maps) = kit.c.get("forwards") {
        for map in maps.as_array().ok_or("Некорректные forwards")? {
            let n = map["guest"].as_u64().ok_or("Некорректный порт")?;
            if !(1..=65535).contains(&n) {
                return Err("Некорректный порт".into());
            }
            if n != 22 {
                ports.push(n as u16);
            }
        }
    }
    ports.sort_unstable();
    ports.dedup();
    Ok(ports)
}
fn counter_command(ports: &[u16], initialize: bool) -> String {
    let mut commands = vec!["set -eu".to_owned()];
    if initialize {
        commands.push(format!(
            "iptables -w 5 -t mangle -N {CHAIN} 2>/dev/null || true"
        ));
        commands.push(format!("iptables -w 5 -t mangle -F {CHAIN}"));
        for port in ports.iter().copied().filter(|p| *p != 22) {
            commands.push(format!(
                "iptables -w 5 -t mangle -A {CHAIN} -p tcp --dport {port} -j RETURN"
            ));
        }
        commands.push(format!("iptables -w 5 -t mangle -C PREROUTING -i eth0 -j {CHAIN} 2>/dev/null || iptables -w 5 -t mangle -I PREROUTING 1 -i eth0 -j {CHAIN}"));
    }
    commands.push("iptables-save -c -t mangle".into());
    commands.join("\n")
}
fn read_counter(text: &str, ports: &[u16]) -> Result<u64> {
    if !text.contains(&format!(":{CHAIN} ")) || !text.contains(&format!("-i eth0 -j {CHAIN}")) {
        return Err("Правила учёта активности отсутствуют".into());
    }
    let mut total = 0u64;
    for line in text
        .lines()
        .filter(|line| line.contains(&format!("] -A {CHAIN} ")))
    {
        let count = line
            .strip_prefix('[')
            .and_then(|s| s.split_once(':'))
            .ok_or("Некорректный счётчик iptables")?
            .0
            .parse::<u64>()?;
        total = total.checked_add(count).ok_or("Переполнение счётчика")?;
    }
    for port in ports {
        if !text.lines().any(|line| {
            line.contains(&format!("] -A {CHAIN} "))
                && line.contains(&format!("--dport {port} -j RETURN"))
        }) {
            return Err("Правило учёта порта отсутствует".into());
        }
    }
    Ok(total)
}
#[derive(Clone, PartialEq)]
struct Sample {
    pid: u32,
    ports: Vec<u16>,
    count: u64,
    stamp: u128,
}
struct IdleClock {
    last: Instant,
    previous: Option<Sample>,
}
impl IdleClock {
    fn new(now: Instant) -> Self {
        Self {
            last: now,
            previous: None,
        }
    }
    fn observe(&mut self, now: Instant, sample: Option<Sample>, busy: bool) -> bool {
        if busy || sample != self.previous {
            self.last = now;
        }
        self.previous = sample;
        now.saturating_duration_since(self.last) >= Duration::from_secs(IDLE_SECONDS)
    }
}
pub(super) fn run(base: PathBuf) -> Result<()> {
    let base = super::install::safe_base(&base)?;
    let Some(_singleton) = Lock::try_exclusive(&base.join("vm/idle.lock"))? else {
        return Ok(());
    };
    super::install::no_links(&base.join("vm/idle.pid"))?;
    atomic(
        &base.join("vm/idle.pid"),
        format!("{}\n", std::process::id()).as_bytes(),
        0o600,
    )?;
    let _pid = PidMarker(base.join("vm/idle.pid"));
    let mut clock = IdleClock::new(Instant::now());
    let mut generation: Option<(u32, Vec<u16>)> = None;
    while base.join("config.json").is_file() {
        let result = (|| -> Result<()> {
            let kit = Kit::load(base.clone())?;
            let Some(pid) = kit.pid().filter(|_| enabled(&kit)) else {
                generation = None;
                clock = IdleClock::new(Instant::now());
                return Ok(());
            };
            let Some(_lease) = Lock::try_exclusive(&kit.vm().join("activity.lock"))? else {
                clock.observe(Instant::now(), None, true);
                return Ok(());
            };
            let ports = ports(&kit)?;
            let current = (pid, ports.clone());
            let initialize = generation.as_ref() != Some(&current);
            let count = read_counter(
                &short_output(
                    &mut kit.ssh(&counter_command(&ports, initialize), false),
                    Duration::from_secs(30),
                )?,
                &ports,
            )?;
            let marker = kit.vm().join("activity");
            let stamp = match fs::metadata(marker) {
                Ok(meta) => meta
                    .modified()?
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_nanos(),
                Err(e) if e.kind() == io::ErrorKind::NotFound => 0,
                Err(e) => return Err(e.into()),
            };
            let expired = clock.observe(
                Instant::now(),
                Some(Sample {
                    pid,
                    ports,
                    count,
                    stamp,
                }),
                false,
            );
            generation = Some(current);
            let latest = Kit::load(base.clone())?;
            if expired
                && enabled(&latest)
                && latest.pid() == Some(pid)
                && self::ports(&latest)? == generation.as_ref().ok_or("Нет поколения")?.1
            {
                println!("30 минут без обращений: корректно выключаю VM");
                latest.stop(false)?;
                generation = None;
                clock = IdleClock::new(Instant::now());
            }
            Ok(())
        })();
        if let Err(error) = result {
            println!("Автоостановка: {error}");
            generation = None;
            clock = IdleClock::new(Instant::now());
        }
        thread::sleep(Duration::from_secs(POLL_SECONDS));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sample(count: u64) -> Sample {
        Sample {
            pid: 12,
            ports: vec![8080],
            count,
            stamp: 0,
        }
    }
    #[test]
    fn clock_conservative() {
        let now = Instant::now();
        let mut clock = IdleClock::new(now);
        assert!(!clock.observe(now, Some(sample(0)), false));
        assert!(!clock.observe(now + Duration::from_secs(1799), Some(sample(0)), false));
        assert!(clock.observe(now + Duration::from_secs(1800), Some(sample(0)), false));
        assert!(!clock.observe(now + Duration::from_secs(1801), Some(sample(1)), false));
        assert!(!clock.observe(now + Duration::from_secs(3601), None, true));
    }
    #[test]
    fn accounting_requires_live_rules() {
        let rules = ":HC_IDLE - [0:0]\n[10:500] -A PREROUTING -i eth0 -j HC_IDLE\n[4:200] -A HC_IDLE -p tcp -m tcp --dport 8080 -j RETURN\n";
        assert_eq!(read_counter(rules, &[8080]).unwrap(), 4);
        assert!(read_counter(rules, &[8081]).is_err());
        assert!(read_counter("", &[]).is_err());
        assert!(!counter_command(&[22, 8080], true).contains("--dport 22"));
    }
}
