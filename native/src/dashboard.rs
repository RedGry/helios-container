//! Selected Docker inventory and bounded, authenticated-by-gateway operations.
use crate::{shell, Kit, Lease, Result};
#[path = "release_notice.rs"]
mod release_notice;
use release_notice::ReleaseNotice;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    fs,
    io::Read,
    path::PathBuf,
    process::Stdio,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const PS: &str = r#"{"ID":{{json .ID}},"Names":{{json .Names}},"Image":{{json .Image}},"State":{{json .State}},"Status":{{json .Status}},"Ports":{{json .Ports}},"CreatedAt":{{json .CreatedAt}},"protocol":{{json (.Label "helios-container.protocol")}},"polling":{{json (.Label "helios-container.polling")}},"project":{{json (.Label "com.docker.compose.project")}},"service":{{json (.Label "com.docker.compose.service")}}}"#;
const IMAGES: &str = r#"{"ID":{{json .ID}},"Repository":{{json .Repository}},"Tag":{{json .Tag}},"CreatedAt":{{json .CreatedAt}},"Size":{{json .Size}}}"#;
const VOLUMES: &str = r#"{"Name":{{json .Name}},"Driver":{{json .Driver}},"Scope":{{json .Scope}},"project":{{json (.Label "com.docker.compose.project")}}}"#;
// Whitelist mount fields in the guest itself. Host paths and environment never cross SSH.
const DETAILS: &str = r#"{"ID":{{json .Id}},"image_id":{{json .Image}},"started_at":{{json .State.StartedAt}},"mounts":[{{range $i,$m := .Mounts}}{{if $i}},{{end}}{"Type":{{json $m.Type}},"Name":{{if eq $m.Type "volume"}}{{json $m.Name}}{{else}}""{{end}},"Destination":{{json $m.Destination}},"RW":{{json $m.RW}}}{{end}}]}"#;
const META: &str = r#"{"Name":{{json .Name}},"CreatedAt":{{json .CreatedAt}}}"#;
const METRICS: &[&str] = &["CPUPerc", "MemUsage", "MemPerc", "NetIO", "BlockIO", "PIDs"];
const LOG_LIMIT: usize = 128 * 1024;

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn s(v: &Value) -> &str {
    v.as_str().unwrap_or("")
}
fn rows(raw: &str) -> Result<Vec<Value>> {
    raw.lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).map_err(Into::into))
        .collect()
}
fn cmd(args: &[&str]) -> String {
    shell(&args.iter().map(|v| v.to_string()).collect::<Vec<_>>())
}
fn hex(v: &str, low: usize, high: usize) -> bool {
    (low..=high).contains(&v.len())
        && v.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn metric(row: &Value) -> Value {
    let mut v = json!({});
    for key in METRICS {
        v[*key] = row[*key].clone();
    }
    v
}
pub(crate) fn bytes_value(raw: &str) -> Option<u64> {
    let raw = raw.trim();
    let split = raw.find(|c: char| !c.is_ascii_digit() && c != '.')?;
    let number: f64 = raw[..split].parse().ok()?;
    let unit = match raw[split..].trim() {
        "B" => 1.,
        "kB" => 1e3,
        "MB" => 1e6,
        "GB" => 1e9,
        "TB" => 1e12,
        "KiB" => 1024.,
        "MiB" => 1048576.,
        "GiB" => 1073741824.,
        "TiB" => 1099511627776.,
        _ => return None,
    };
    (number.is_finite() && number >= 0. && number * unit <= u64::MAX as f64)
        .then_some((number * unit) as u64)
}

// Drain stdout concurrently with wait: a pipe larger than its OS buffer must not deadlock.
fn ssh(kit: &Kit, command: &str, seconds: u64, limit: usize) -> Result<String> {
    let mut child = kit
        .ssh(command, false)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let mut pipe = child.stdout.take().ok_or("Нет stdout")?;
    let reader = thread::spawn(move || -> std::io::Result<Vec<u8>> {
        let mut out = Vec::new();
        let mut chunk = [0u8; 8192];
        loop {
            let n = pipe.read(&mut chunk)?;
            if n == 0 {
                break;
            }
            if out.len() + n <= limit {
                out.extend_from_slice(&chunk[..n]);
            } else {
                return Err(std::io::Error::other("Ответ слишком большой"));
            }
        }
        Ok(out)
    });
    let deadline = Instant::now() + Duration::from_secs(seconds);
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("Таймаут команды".into());
        }
        thread::sleep(Duration::from_millis(25));
    };
    let bytes = reader.join().map_err(|_| "Не удалось прочитать ответ")??;
    if !status.success() {
        return Err("Команда не выполнена".into());
    }
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

struct Cache {
    value: Option<Value>,
    due: Instant,
    full_due: Instant,
    metrics_due: Instant,
    metrics_running: bool,
    refreshing: bool,
    cpu: Option<(u64, u64)>,
}
struct Storage {
    value: Value,
    due: Instant,
    running: bool,
}
pub struct Dashboard {
    base: PathBuf,
    cache: Mutex<Cache>,
    storage: Mutex<Storage>,
    jobs: Mutex<VecDeque<Value>>,
    releases: Arc<ReleaseNotice>,
}
impl Dashboard {
    pub fn new(base: PathBuf) -> Arc<Self> {
        Arc::new(Self {
            releases: ReleaseNotice::new(base.clone()),
            base,
            cache: Mutex::new(Cache {
                value: None,
                due: Instant::now(),
                full_due: Instant::now(),
                metrics_due: Instant::now(),
                metrics_running: false,
                refreshing: false,
                cpu: None,
            }),
            storage: Mutex::new(Storage {
                value: json!({"volumes":{},"images":{},"updated_at":null,"error":null}),
                due: Instant::now(),
                running: false,
            }),
            jobs: Mutex::new(VecDeque::new()),
        })
    }
    fn initial(&self) -> Value {
        let kit = Kit::load(self.base.clone()).ok();
        json!({"vm":{"running":kit.as_ref().is_some_and(|k| k.pid().is_some()),"cpus":kit.as_ref().map(|k|k.c["cpus"].clone()).unwrap_or(json!(0)),"memory_mib":kit.as_ref().map(|k|k.c["memory_mib"].clone()).unwrap_or(json!(0)),"docker_running":null},"containers":[],"images":[],"volumes":[],"error":null,"kit_version":self.version(),"updated_at":null,"loading":true})
    }
    fn version(&self) -> String {
        fs::read_to_string(self.base.join("VERSION"))
            .unwrap_or_else(|_| "dev".into())
            .trim()
            .chars()
            .take(40)
            .collect()
    }
    pub fn snapshot(self: &Arc<Self>) -> Value {
        let mut cache = self.cache.lock().unwrap();
        if cache.value.is_none() {
            cache.value = Some(self.initial());
        }
        if !cache.refreshing && Instant::now() >= cache.due {
            cache.refreshing = true;
            let owner = Arc::clone(self);
            thread::spawn(move || owner.refresh());
        }
        let mut value = cache.value.clone().unwrap();
        value["refreshing"] = json!(cache.refreshing);
        drop(cache);
        value["update"] = self.releases.snapshot();
        self.with_storage(value)
    }
    fn refresh(self: Arc<Self>) {
        let result = (|| -> Result<()> {
            let kit = Kit::load(self.base.clone())?;
            let loading = self
                .cache
                .lock()
                .unwrap()
                .value
                .as_ref()
                .is_some_and(|v| v["loading"] == true);
            if loading && kit.pid().is_some() {
                if let Ok(raw) = ssh(
                    &kit,
                    &cmd(&[
                        "docker",
                        "container",
                        "ls",
                        "-a",
                        "--no-trunc",
                        "--format",
                        PS,
                    ]),
                    10,
                    4 * 1024 * 1024,
                ) {
                    if let Ok(mut containers) = rows(&raw) {
                        for row in &mut containers {
                            normalize(row);
                            row["metrics"] = metric(&Value::Null);
                            row["mounts"] = json!([]);
                            row["image_id"] = json!("");
                            row["started_at"] = json!("");
                        }
                        let mut cache = self.cache.lock().unwrap();
                        let value = cache.value.as_mut().unwrap();
                        value["containers"] = json!(containers);
                        value["loading"] = json!(false);
                        value["inventory_pending"] = json!(true);
                        value["metrics_ready"] = json!(false);
                        value["updated_at"] = json!(now());
                    }
                }
            }
            let full = {
                let cache = self.cache.lock().unwrap();
                loading || Instant::now() >= cache.full_due
            };
            let mut value = if full {
                self.collect(&kit)?
            } else {
                self.collect_warm(&kit)?
            };
            let metrics = value["vm"]["running"] == true && value["error"].is_null();
            {
                let mut cache = self.cache.lock().unwrap();
                if full {
                    cache.full_due = Instant::now()
                        + Duration::from_secs(if value["error"].is_null() { 30 } else { 10 });
                }
                // A parallel metrics worker may have finished while inventory was over SSH.
                if let Some(latest) = cache.value.as_ref() {
                    preserve_newer_metrics(&mut value, latest);
                }
                cache.value = Some(value);
            }
            if metrics {
                self.start_metrics(kit);
            }
            Ok(())
        })();
        let mut cache = self.cache.lock().unwrap();
        if result.is_err() {
            if let Some(value) = cache.value.as_mut() {
                value["error"] =
                    json!("Не удалось обновить данные. Повторная проверка через 10 секунд.");
            }
            cache.due = Instant::now() + Duration::from_secs(10);
        } else {
            // Slow statistics have their own single worker and never delay state refresh.
            cache.due = Instant::now() + Duration::from_secs(2);
        }
        cache.refreshing = false;
    }
    fn collect_warm(&self, kit: &Kit) -> Result<Value> {
        let previous = self
            .cache
            .lock()
            .unwrap()
            .value
            .clone()
            .unwrap_or(Value::Null);
        if kit.pid().is_none() {
            return self.collect(kit);
        }
        let command=format!("printf 'HC_HEALTH\\n'; awk '/MemTotal:/ {{t=$2}} /MemAvailable:/ {{a=$2}} END {{print t; print a}}' /proc/meminfo; head -n 1 /proc/stat; df -k /var/lib/docker | tail -n 1; printf '\\nHC_INVENTORY\\n'; {}",cmd(&["docker","container","ls","-a","--no-trunc","--format",PS]));
        let raw = ssh(kit, &command, 10, 4 * 1024 * 1024)?;
        let (health, listing) = raw.split_once("\nHC_INVENTORY\n").ok_or("Нет данных VM")?;
        let mut data = previous.clone();
        let missing = merge_warm_rows(&mut data, rows(listing)?);
        self.apply_health(&mut data, health)?;
        data["vm"]["running"] = json!(true);
        data["vm"]["docker_running"] = json!(true);
        data["error"] = Value::Null;
        data["loading"] = json!(false);
        data["updated_at"] = json!(now());
        if missing {
            self.cache.lock().unwrap().full_due = Instant::now();
        }
        Ok(data)
    }
    fn apply_health(&self, data: &mut Value, health: &str) -> Result<()> {
        let lines: Vec<_> = health.lines().skip(1).collect();
        let total = lines.first().ok_or("Нет памяти")?.trim().parse::<u64>()?;
        let available = lines.get(1).ok_or("Нет памяти")?.trim().parse::<u64>()?;
        data["vm"]["memory_total_bytes"] = json!(total * 1024);
        data["vm"]["memory_used_bytes"] = json!(total.saturating_sub(available) * 1024);
        let ticks: Vec<u64> = lines
            .get(2)
            .ok_or("Нет CPU")?
            .split_whitespace()
            .skip(1)
            .take(8)
            .map(str::parse)
            .collect::<std::result::Result<_, _>>()?;
        if ticks.len() >= 5 {
            let sample = (ticks.iter().sum::<u64>(), ticks[3] + ticks[4]);
            let mut cache = self.cache.lock().unwrap();
            if let Some(old) = cache.cpu {
                if sample.0 > old.0 {
                    data["vm"]["cpu_percent"] = json!(
                        (10000.
                            * (1.
                                - sample.1.saturating_sub(old.1) as f64
                                    / (sample.0 - old.0) as f64))
                            .round()
                            / 100.
                    );
                }
            }
            cache.cpu = Some(sample);
        }
        let disk: Vec<_> = lines
            .get(3)
            .ok_or("Нет диска")?
            .split_whitespace()
            .collect();
        data["vm"]["disk_total_bytes"] =
            json!(disk.get(1).ok_or("Нет диска")?.parse::<u64>()? * 1024);
        data["vm"]["disk_used_bytes"] =
            json!(disk.get(2).ok_or("Нет диска")?.parse::<u64>()? * 1024);
        Ok(())
    }
    fn collect(&self, kit: &Kit) -> Result<Value> {
        let mut data = json!({"vm":{"running":kit.pid().is_some(),"cpus":kit.c["cpus"],"memory_mib":kit.c["memory_mib"],"cpu_percent":null,"memory_used_bytes":null,"disk_used_bytes":null,"disk_total_bytes":null,"docker_version":null,"docker_running":false},"containers":[],"images":[],"volumes":[],"updated_at":now(),"error":null,"metrics_ready":false,"kit_version":self.version()});
        if data["vm"]["running"] != true {
            return Ok(data);
        }
        let command=format!("printf 'HC_HEALTH\\n'; awk '/MemTotal:/ {{t=$2}} /MemAvailable:/ {{a=$2}} END {{print t; print a}}' /proc/meminfo; head -n 1 /proc/stat; df -k /var/lib/docker | tail -n 1; printf '\\nHC_INVENTORY\\n'; {} && printf '\\nHC_IMAGES\\n' && {} && printf '\\nHC_VOLUMES\\n' && {} && printf '\\nHC_MOUNTS\\n' && docker container ls -aq | xargs -r {} && printf '\\nHC_STATS\\n\\nHC_MEMORY\\n' && awk '/MemTotal:/ {{print $2}}' /proc/meminfo && printf '\\nHC_VERSION\\n' && docker info --format '{{{{.ServerVersion}}}}'",cmd(&["docker","container","ls","-a","--no-trunc","--format",PS]),cmd(&["docker","image","ls","--all","--no-trunc","--format",IMAGES]),cmd(&["docker","volume","ls","--format",VOLUMES]),cmd(&["docker","inspect","--format",DETAILS]));
        // Keep health information even when Docker is stopped (shell exit is ignored here).
        let command = format!("( {command} ); exit 0");
        let mut stage = "ssh";
        let result = (|| -> Result<()> {
            let raw = ssh(kit, &command, 15, 8 * 1024 * 1024)?;
            stage = "health marker";
            let (health, raw) = raw.split_once("\nHC_INVENTORY\n").ok_or("Нет данных VM")?;
            let lines: Vec<_> = health.lines().skip(1).collect();
            stage = "memory health";
            let total = lines.first().ok_or("Нет памяти")?.trim().parse::<u64>()?;
            let available = lines.get(1).ok_or("Нет памяти")?.trim().parse::<u64>()?;
            data["vm"]["memory_total_bytes"] = json!(total * 1024);
            data["vm"]["memory_used_bytes"] = json!(total.saturating_sub(available) * 1024);
            stage = "cpu health";
            let ticks: Vec<u64> = lines
                .get(2)
                .ok_or("Нет CPU")?
                .split_whitespace()
                .skip(1)
                .take(8)
                .map(str::parse)
                .collect::<std::result::Result<_, _>>()?;
            if ticks.len() >= 5 {
                let sample = (ticks.iter().sum::<u64>(), ticks[3] + ticks[4]);
                let mut cache = self.cache.lock().unwrap();
                if let Some(old) = cache.cpu {
                    if sample.0 > old.0 {
                        data["vm"]["cpu_percent"] = json!(
                            (10000.
                                * (1.
                                    - sample.1.saturating_sub(old.1) as f64
                                        / (sample.0 - old.0) as f64))
                                .round()
                                / 100.
                        );
                    }
                }
                cache.cpu = Some(sample);
            }
            stage = "disk health";
            let disk: Vec<_> = lines
                .get(3)
                .ok_or("Нет диска")?
                .split_whitespace()
                .collect();
            data["vm"]["disk_total_bytes"] =
                json!(disk.get(1).ok_or("Нет диска")?.parse::<u64>()? * 1024);
            data["vm"]["disk_used_bytes"] =
                json!(disk.get(2).ok_or("Нет диска")?.parse::<u64>()? * 1024);
            stage = "inventory sections";
            let (listing, rest) = raw.split_once("\nHC_IMAGES\n").ok_or("Docker недоступен")?;
            let (images, rest) = rest.split_once("\nHC_VOLUMES\n").ok_or("Нет образов")?;
            let (volumes, rest) = rest.split_once("\nHC_MOUNTS\n").ok_or("Нет volumes")?;
            let (mounts, rest) = rest.split_once("\nHC_STATS\n").ok_or("Нет mounts")?;
            let (_, memory) = rest.split_once("\nHC_MEMORY\n").ok_or("Нет памяти")?;
            let (memory, version) = memory.split_once("\nHC_VERSION\n").ok_or("Нет версии")?;
            data["vm"]["memory_total_bytes"] = json!(memory.trim().parse::<u64>()? * 1024);
            data["vm"]["docker_version"] =
                json!(version.trim().chars().take(40).collect::<String>());
            data["vm"]["docker_running"] = json!(true);
            stage = "mount JSON";
            let details = rows(mounts)?;
            stage = "container JSON";
            let mut containers = rows(listing)?;
            let previous = self
                .cache
                .lock()
                .unwrap()
                .value
                .clone()
                .unwrap_or(Value::Null);
            data["metrics_ready"] = previous["metrics_ready"].as_bool().unwrap_or(false).into();
            data["metrics_updated_at"] = previous["metrics_updated_at"].clone();
            for row in &mut containers {
                normalize(row);
                let old = previous["containers"]
                    .as_array()
                    .and_then(|cs| cs.iter().find(|c| c["ID"] == row["ID"]));
                row["metrics"] = old
                    .map(|v| metric(&v["metrics"]))
                    .unwrap_or_else(|| metric(&Value::Null));
                let detail = details.iter().find(|d| d["ID"] == row["ID"]);
                row["image_id"] = detail.map(|d| d["image_id"].clone()).unwrap_or(json!(""));
                row["started_at"] = detail.map(|d| d["started_at"].clone()).unwrap_or(json!(""));
                row["mounts"]=json!(detail.and_then(|d|d["mounts"].as_array()).map(|ms|ms.iter().map(|m|json!({"Type":m["Type"],"Name":m["Name"],"Destination":m["Destination"],"RW":m["RW"]})).collect::<Vec<_>>()).unwrap_or_default());
            }
            stage = "image JSON";
            let mut images = rows(images)?;
            stage = "volume JSON";
            let mut volumes = rows(volumes)?;
            for image in &mut images {
                image["containers"] = json!(containers
                    .iter()
                    .filter(|c| c["image_id"] == image["ID"])
                    .map(|c| c["Names"].clone())
                    .collect::<Vec<_>>());
            }
            for volume in &mut volumes {
                volume["containers"] = json!(containers
                    .iter()
                    .filter(|c| c["mounts"].as_array().is_some_and(|ms| ms
                        .iter()
                        .any(|m| m["Type"] == "volume" && m["Name"] == volume["Name"])))
                    .map(|c| c["Names"].clone())
                    .collect::<Vec<_>>());
            }
            data["containers"] = json!(containers);
            data["images"] = json!(images);
            data["volumes"] = json!(volumes);
            Ok(())
        })();
        if let Err(error) = result {
            // Diagnostics contain only a stage and parser error, never Docker output or secrets.
            eprintln!("dashboard collect failed at {stage}: {error}");
            let previous = self
                .cache
                .lock()
                .unwrap()
                .value
                .clone()
                .unwrap_or(Value::Null);
            preserve_inventory(&mut data, &previous);
            data["error"] = json!("Docker пока не отвечает. VM может загружаться.");
        }
        Ok(data)
    }
    fn start_metrics(self: &Arc<Self>, kit: Kit) {
        let mut cache = self.cache.lock().unwrap();
        if cache.metrics_running || Instant::now() < cache.metrics_due {
            return;
        }
        cache.metrics_running = true;
        drop(cache);
        let owner = Arc::clone(self);
        thread::spawn(move || {
            owner.metrics(&kit);
            let mut cache = owner.cache.lock().unwrap();
            cache.metrics_running = false;
            cache.metrics_due = Instant::now() + Duration::from_secs(5);
        });
    }
    fn metrics(&self, kit: &Kit) {
        let result = ssh(
            kit,
            "docker stats --no-stream --format '{{json .}}'",
            15,
            4 * 1024 * 1024,
        )
        .and_then(|raw| rows(&raw));
        let mut cache = self.cache.lock().unwrap();
        let data = cache.value.as_mut().unwrap();
        // A stop may have completed while stats was running. Do not revive stale metrics.
        if data["vm"]["running"] != true || data["vm"]["docker_running"] != true {
            return;
        }
        if let Ok(usage) = result {
            for c in data["containers"].as_array_mut().unwrap() {
                if c["State"] != "running" {
                    c["metrics"] = metric(&Value::Null);
                    continue;
                }
                c["metrics"] = usage
                    .iter()
                    .find(|m| s(&c["ID"]).starts_with(s(&m["ID"])) && !s(&m["ID"]).is_empty())
                    .map(metric)
                    .unwrap_or_else(|| metric(&Value::Null));
            }
            data["metrics_ready"] = json!(true);
            data["metrics_updated_at"] = json!(now());
            data["metrics_error"] = Value::Null;
        } else {
            data["metrics_error"] =
                json!("Статистика пока недоступна. Список контейнеров загружен.");
        }
    }
    fn with_storage(self: &Arc<Self>, mut data: Value) -> Value {
        let mut storage = self.storage.lock().unwrap();
        data["storage"] = json!({"updated_at":storage.value["updated_at"],"error":storage.value["error"],"pending":storage.running});
        let mut missing = false;
        for volume in data["volumes"].as_array_mut().unwrap() {
            let item = storage.value["volumes"].get(s(&volume["Name"]));
            if let Some(item) = item {
                for key in ["Size", "size_bytes", "CreatedAt"] {
                    volume[key] = item[key].clone();
                }
            } else {
                missing = true;
                for key in ["Size", "size_bytes", "CreatedAt"] {
                    volume[key] = Value::Null;
                }
            }
        }
        for image in data["images"].as_array_mut().unwrap() {
            if let Some(item) = storage.value["images"].get(s(&image["ID"])) {
                for key in ["SharedSize", "UniqueSize"] {
                    image[key] = item[key].clone();
                }
            }
            image["size_bytes"] = json!(bytes_value(s(&image["Size"])));
        }
        if data["vm"]["running"] == true
            && data["loading"] != true
            && data["inventory_pending"] != true
            && data["error"].is_null()
            && !storage.running
            && (Instant::now() >= storage.due || missing && storage.value["error"].is_null())
        {
            storage.running = true;
            data["storage"]["pending"] = json!(true);
            let owner = Arc::clone(self);
            thread::spawn(move || owner.storage_update());
        }
        drop(storage);
        add_resources(&mut data);
        data
    }
    fn storage_update(&self) {
        let result = (|| -> Result<Value> {
            let kit = Kit::load(self.base.clone())?;
            if kit.pid().is_none() {
                return Err("VM остановлена".into());
            }
            let command=format!("docker system df --verbose --format '{{{{json .}}}}' && printf '\\nHC_VOLUME_META\\n' && docker volume ls -q | xargs -r {}",cmd(&["docker","volume","inspect","--format",META]));
            let raw = ssh(&kit, &command, 45, 8 * 1024 * 1024)?;
            let (raw, metadata) = raw.split_once("\nHC_VOLUME_META\n").ok_or("Нет размеров")?;
            let disk: Value = serde_json::from_str(raw)?;
            let dates = rows(metadata)?;
            let mut value = json!({"volumes":{},"images":{},"updated_at":now(),"error":null});
            if let Some(vs) = disk["Volumes"].as_array() {
                for v in vs {
                    value["volumes"][s(&v["Name"])] = json!({"Size":v["Size"],"size_bytes":bytes_value(s(&v["Size"])),"CreatedAt":dates.iter().find(|d|d["Name"]==v["Name"]).map(|d|d["CreatedAt"].clone())});
                }
            }
            if let Some(images) = disk["Images"].as_array() {
                for i in images {
                    value["images"][s(&i["ID"])] =
                        json!({"SharedSize":i["SharedSize"],"UniqueSize":i["UniqueSize"]});
                }
            }
            Ok(value)
        })();
        let mut storage = self.storage.lock().unwrap();
        match result {
            Ok(value) => storage.value = value,
            Err(_) => {
                storage.value["error"] =
                    json!("Размеры пока недоступны. Повторная проверка через минуту.")
            }
        }
        storage.due = Instant::now() + Duration::from_secs(60);
        storage.running = false;
    }
    pub fn action(self: &Arc<Self>, payload: Value) -> Result<Value> {
        let action = s(&payload["action"]).to_owned();
        if !payload.is_object()
            || !["start", "stop", "restart", "delete"].contains(&action.as_str())
        {
            return Err("Недопустимая операция.".into());
        }
        if payload.get("kind").is_some_and(|value| !value.is_string()) {
            return Err("Некорректный контейнер или проект.".into());
        }
        let kind = payload
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or("container")
            .to_owned();
        let target = s(&payload["id"]);
        let mut ids = Vec::new();
        let mut expected = None;
        if ["vm", "engine"].contains(&kind.as_str()) {
            if target != kind || !["start", "stop"].contains(&action.as_str()) {
                return Err("Недопустимая операция VM или Docker.".into());
            }
            if action == "stop" && s(&payload["confirm"]) != kind {
                return Err("Подтвердите остановку приложений.".into());
            }
            if kind == "engine" && Kit::load(self.base.clone())?.pid().is_none() {
                return Err("Сначала запустите VM.".into());
            }
        } else {
            let data = self.snapshot();
            let selected = select_action(&data, &payload)?;
            ids = selected.0;
            expected = selected.1;
        }
        let mut jobs = self.jobs.lock().unwrap();
        if jobs.iter().any(|j| j["status"] == "running") {
            return Err("Дождитесь завершения текущей операции.".into());
        }
        while jobs.len() >= 16 {
            jobs.pop_front();
        }
        let mut random = [0u8; 16];
        fs::File::open("/dev/urandom")?.read_exact(&mut random)?;
        let token = random
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let job = json!({"id":token,"action":action,"status":"running","error":null});
        jobs.push_back(job.clone());
        drop(jobs);
        let owner = Arc::clone(self);
        thread::spawn(move || owner.perform(token, ids, action, kind, expected));
        Ok(job)
    }
    fn perform(
        &self,
        token: String,
        ids: Vec<String>,
        action: String,
        kind: String,
        expected: Option<String>,
    ) {
        let result = (|| -> Result<()> {
            let kit = Kit::load(self.base.clone())?;
            let _lease = Lease::acquire(&self.base)?;
            if kind == "vm" {
                return if action == "start" {
                    kit.start(false)
                } else {
                    kit.stop(false)
                };
            }
            if kit.pid().is_none() {
                return Err("VM остановлена".into());
            }
            if kind == "engine" {
                ssh(
                    &kit,
                    &format!("rc-service docker {action}"),
                    120,
                    1024 * 1024,
                )?;
                return Ok(());
            }
            if action == "delete" && kind == "image" {
                let current = ssh(
                    &kit,
                    &cmd(&["docker", "image", "inspect", "--format", "{{.Id}}", &ids[0]]),
                    10,
                    1024,
                )?;
                if Some(current.trim()) != expected.as_deref() {
                    return Err("Образ изменился".into());
                }
            }
            // Recheck the exact project membership without putting a project label into shell code.
            if action == "delete" && kind == "project" {
                let raw = ssh(
                    &kit,
                    &cmd(&[
                        "docker",
                        "container",
                        "ls",
                        "-a",
                        "--no-trunc",
                        "--format",
                        PS,
                    ]),
                    10,
                    4 * 1024 * 1024,
                )?;
                let mut live = rows(&raw)?
                    .iter()
                    .filter(|c| Some(s(&c["project"])) == expected.as_deref())
                    .map(|c| s(&c["ID"]).to_owned())
                    .collect::<Vec<_>>();
                let mut approved = ids.clone();
                live.sort();
                approved.sort();
                if live != approved {
                    return Err("Состав проекта изменился".into());
                }
            }
            // Recheck states immediately before removal. Docker rm without force is the final race guard.
            if action == "delete" && ["container", "project"].contains(&kind.as_str()) {
                let mut args = vec![
                    "docker".into(),
                    "inspect".into(),
                    "--format".into(),
                    "{{.State.Status}}".into(),
                ];
                args.extend(ids.clone());
                let states = ssh(&kit, &shell(&args), 10, 65536)?;
                if states
                    .lines()
                    .any(|state| !["exited", "created", "dead"].contains(&state.trim()))
                {
                    return Err("Контейнер запущен".into());
                }
            }
            let mut args = if action == "delete" {
                vec![
                    "docker".into(),
                    if kind == "project" {
                        "container".into()
                    } else {
                        kind.clone()
                    },
                    "rm".into(),
                    "--".into(),
                ]
            } else {
                let mut args = vec!["docker".into(), action.clone()];
                if ["stop", "restart"].contains(&action.as_str()) {
                    args.extend(["--time".into(), "5".into()]);
                }
                args
            };
            args.extend(ids);
            ssh(&kit, &shell(&args), 90, 1024 * 1024)?;
            Ok(())
        })();
        if let Some(job) = self
            .jobs
            .lock()
            .unwrap()
            .iter_mut()
            .find(|j| j["id"] == token)
        {
            job["status"] = json!(if result.is_ok() { "done" } else { "error" });
            job["error"] = if result.is_ok() {
                Value::Null
            } else {
                json!("Операция не завершилась. Обновите состояние VM и Docker.")
            };
        }
        {
            let mut cache = self.cache.lock().unwrap();
            cache.due = Instant::now();
            cache.metrics_due = Instant::now();
            if ["image", "volume", "vm", "engine"].contains(&kind.as_str()) {
                cache.full_due = Instant::now();
            }
        }
        self.storage.lock().unwrap().due = Instant::now();
    }
    pub fn job(&self, token: &str) -> Result<Value> {
        if !hex(token, 32, 32) {
            return Err("Некорректный ID операции.".into());
        }
        self.jobs
            .lock()
            .unwrap()
            .iter()
            .find(|j| j["id"] == token)
            .cloned()
            .ok_or_else(|| "Операция не найдена. Обновите состояние контейнеров.".into())
    }
    pub fn logs(&self, id: &str, tail: &str) -> Result<Value> {
        let count = tail.parse::<u16>().unwrap_or(0);
        if !hex(id, 12, 64)
            || tail.len() > 4
            || !tail.bytes().all(|b| b.is_ascii_digit())
            || !(1..=1000).contains(&count)
        {
            return Err("Укажите ID контейнера и от 1 до 1000 строк.".into());
        }
        let kit = Kit::load(self.base.clone())?;
        if kit.pid().is_none() {
            return Err("VM остановлена.".into());
        }
        let command = format!(
            "{} 2>&1 | tail -c {}",
            cmd(&["docker", "logs", "--timestamps", "--tail", tail, id]),
            LOG_LIMIT + 1
        );
        let raw = ssh(&kit, &command, 8, LOG_LIMIT + 1)?;
        let bytes = raw.as_bytes();
        let text = String::from_utf8_lossy(&bytes[bytes.len().saturating_sub(LOG_LIMIT)..]);
        Ok(json!({"id":id,"text":text,"truncated":bytes.len()>LOG_LIMIT,"tail":count}))
    }
}
fn normalize(row: &mut Value) {
    if !["http", "https", "tcp", "udp"].contains(&s(&row["protocol"])) {
        row["protocol"] = json!("unknown");
    }
    if !["true", "false"].contains(&s(&row["polling"])) {
        row["polling"] = json!("unknown");
    }
}
fn preserve_newer_metrics(data: &mut Value, latest: &Value) {
    if data["vm"]["running"] != true || data["vm"]["docker_running"] != true {
        return;
    }
    if latest["metrics_updated_at"].as_u64().unwrap_or(0)
        <= data["metrics_updated_at"].as_u64().unwrap_or(0)
    {
        return;
    }
    if let Some(containers) = data["containers"].as_array_mut() {
        for container in containers {
            container["metrics"] = if container["State"] == "running" {
                latest["containers"]
                    .as_array()
                    .and_then(|cs| cs.iter().find(|c| c["ID"] == container["ID"]))
                    .map(|c| metric(&c["metrics"]))
                    .unwrap_or_else(|| metric(&Value::Null))
            } else {
                metric(&Value::Null)
            };
        }
    }
    for key in ["metrics_ready", "metrics_updated_at", "metrics_error"] {
        data[key] = latest[key].clone();
    }
}
// Refresh process state without throwing away selected metadata or waiting for inspect.
// Unknown IDs trigger a full metadata pass and disable resource deletion until it finishes.
fn merge_warm_rows(data: &mut Value, mut containers: Vec<Value>) -> bool {
    let previous = data["containers"].as_array().cloned().unwrap_or_default();
    let mut missing = false;
    for row in &mut containers {
        normalize(row);
        if let Some(old) = previous.iter().find(|old| old["ID"] == row["ID"]) {
            for key in ["mounts", "image_id", "started_at"] {
                row[key] = old[key].clone();
            }
            row["metrics"] = if row["State"] == "running" {
                metric(&old["metrics"])
            } else {
                metric(&Value::Null)
            };
            if s(&row["image_id"]).is_empty() {
                missing = true;
            }
        } else {
            missing = true;
            row["mounts"] = json!([]);
            row["image_id"] = json!("");
            row["started_at"] = json!("");
            row["metrics"] = metric(&Value::Null);
        }
    }
    for image in data["images"].as_array_mut().unwrap() {
        image["containers"] = json!(containers
            .iter()
            .filter(|c| c["image_id"] == image["ID"])
            .map(|c| c["Names"].clone())
            .collect::<Vec<_>>());
    }
    for volume in data["volumes"].as_array_mut().unwrap() {
        volume["containers"] = json!(containers
            .iter()
            .filter(|c| c["mounts"].as_array().is_some_and(|ms| ms
                .iter()
                .any(|m| m["Type"] == "volume" && m["Name"] == volume["Name"])))
            .map(|c| c["Names"].clone())
            .collect::<Vec<_>>());
    }
    data["containers"] = json!(containers);
    data["inventory_pending"] = json!(missing);
    missing
}
fn preserve_inventory(data: &mut Value, previous: &Value) {
    for key in [
        "containers",
        "images",
        "volumes",
        "metrics_ready",
        "metrics_updated_at",
        "updated_at",
    ] {
        if let Some(value) = previous.get(key) {
            data[key] = value.clone();
        }
    }
    data["loading"] = json!(false);
    data["inventory_pending"] = json!(false);
}
fn image_reference(image: &Value) -> String {
    if s(&image["Repository"]) == "<none>" || s(&image["Tag"]) == "<none>" {
        s(&image["ID"]).into()
    } else {
        format!("{}:{}", s(&image["Repository"]), s(&image["Tag"]))
    }
}
fn add_resources(data: &mut Value) {
    let cs = data["containers"].as_array().unwrap();
    let cpu = cs
        .iter()
        .filter_map(|c| {
            s(&c["metrics"]["CPUPerc"])
                .trim_end_matches('%')
                .parse::<f64>()
                .ok()
        })
        .filter(|v| v.is_finite())
        .sum::<f64>();
    let memory = cs
        .iter()
        .filter_map(|c| bytes_value(s(&c["metrics"]["MemUsage"]).split('/').next().unwrap_or("")))
        .sum::<u64>();
    data["resources"] = json!({"cpu_percent":(cpu*100.).round()/100.,"cpu_capacity_percent":data["vm"]["cpus"].as_u64().unwrap_or(0)*100,"memory_used_bytes":memory,"memory_total_bytes":data["vm"]["memory_total_bytes"].as_u64().unwrap_or(data["vm"]["memory_mib"].as_u64().unwrap_or(0)*1024*1024)});
}
fn select_action(data: &Value, payload: &Value) -> Result<(Vec<String>, Option<String>)> {
    let kind = payload
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("container");
    let target = s(&payload["id"]);
    let action = s(&payload["action"]);
    if !["container", "project", "image", "volume"].contains(&kind)
        || target.is_empty()
        || target.len() > 200
    {
        return Err("Некорректный контейнер или проект.".into());
    }
    if kind == "container" && !hex(target, 12, 64) {
        return Err("Некорректный ID контейнера.".into());
    }
    if data["loading"] == true {
        return Err("Дождитесь загрузки списка контейнеров.".into());
    }
    if data["inventory_pending"] == true && ["image", "volume"].contains(&kind) {
        return Err("Дождитесь загрузки сведений о контейнерах.".into());
    }
    if data["vm"]["running"] != true || !data["error"].is_null() {
        return Err("Docker недоступен. Сначала запустите VM.".into());
    }
    let cs = data["containers"]
        .as_array()
        .ok_or("Нет списка контейнеров")?;
    if ["container", "project"].contains(&kind) {
        let selected: Vec<_> = cs
            .iter()
            .filter(|c| {
                if kind == "project" {
                    s(&c["project"]) == target
                } else {
                    s(&c["ID"]) == target
                }
            })
            .collect();
        let ids: Vec<String> = selected.iter().map(|c| s(&c["ID"]).to_owned()).collect();
        if ids.is_empty() || ids.iter().any(|id| !hex(id, 64, 64)) {
            return Err("Контейнер или проект больше не существует. Обновите список.".into());
        }
        if action == "delete" {
            if selected
                .iter()
                .any(|c| !["exited", "created", "dead"].contains(&s(&c["State"])))
            {
                return Err("Сначала остановите все выбранные контейнеры.".into());
            }
            let confirmation = if kind == "project" {
                target
            } else {
                s(&selected[0]["Names"])
            };
            if s(&payload["confirm"]) != confirmation {
                return Err("Подтвердите удаление выбранного объекта.".into());
            }
            if kind == "project" {
                let mut sorted = ids.clone();
                sorted.sort();
                if payload["container_ids"] != json!(sorted) {
                    return Err(
                        "Состав проекта изменился. Обновите список и подтвердите удаление снова."
                            .into(),
                    );
                }
            }
        }
        return Ok((
            ids,
            if action == "delete" && kind == "project" {
                Some(target.to_owned())
            } else {
                None
            },
        ));
    }
    if action != "delete" {
        return Err("Для образов и volumes доступно только удаление.".into());
    }
    let (confirmation, expected) = if kind == "image" {
        if !target
            .strip_prefix("sha256:")
            .is_some_and(|id| hex(id, 64, 64))
        {
            return Err("Некорректный ID образа.".into());
        }
        let image = data["images"]
            .as_array()
            .and_then(|images| {
                images.iter().find(|i| {
                    s(&i["ID"]) == target && image_reference(i) == s(&payload["reference"])
                })
            })
            .ok_or("Образ больше не существует. Обновите каталог.")?;
        if image["containers"]
            .as_array()
            .is_some_and(|cs| !cs.is_empty())
        {
            return Err("Образ используется контейнерами, включая остановленные.".into());
        }
        (image_reference(image), Some(target.to_owned()))
    } else {
        if !target.as_bytes()[0].is_ascii_alphanumeric()
            || !target
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
        {
            return Err("Некорректное имя volume.".into());
        }
        let volume = data["volumes"]
            .as_array()
            .and_then(|vs| vs.iter().find(|v| s(&v["Name"]) == target))
            .ok_or("Volume больше не существует. Обновите каталог.")?;
        if volume["containers"]
            .as_array()
            .is_some_and(|cs| !cs.is_empty())
        {
            return Err("Volume используется контейнерами, включая остановленные.".into());
        }
        (target.to_owned(), None)
    };
    if s(&payload["confirm"]) != confirmation {
        return Err("Подтвердите удаление выбранного объекта.".into());
    }
    Ok((vec![confirmation], expected))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn state_refresh_preserves_parallel_metrics_without_reviving_stopped_rows() {
        let id = "a".repeat(64);
        let latest = json!({"metrics_updated_at":20,"metrics_ready":true,"containers":[{"ID":id,"metrics":{"CPUPerc":"12%"}}]});
        let mut data = json!({"vm":{"running":true,"docker_running":true},"metrics_updated_at":10,"containers":[{"ID":id,"State":"running","metrics":{"CPUPerc":"1%"}}]});
        preserve_newer_metrics(&mut data, &latest);
        assert_eq!(data["containers"][0]["metrics"]["CPUPerc"], "12%");
        assert_eq!(data["metrics_updated_at"], 20);
        data["metrics_updated_at"] = json!(10);
        data["containers"][0]["State"] = json!("exited");
        preserve_newer_metrics(&mut data, &latest);
        assert!(data["containers"][0]["metrics"]["CPUPerc"].is_null());
    }
    #[test]
    fn cheap_refresh_keeps_metadata_updates_references_and_marks_unknown_ids() {
        let id = "a".repeat(64);
        let image = format!("sha256:{}", "b".repeat(64));
        let old = json!({"ID":id,"Names":"demo","State":"running","image_id":image,"started_at":"started","mounts":[{"Type":"volume","Name":"db","Destination":"/data","RW":true}],"metrics":{"CPUPerc":"12%","MemUsage":"12MiB / 4GiB"}});
        let mut data = json!({"containers":[old],"images":[{"ID":image,"containers":["demo"]}],"volumes":[{"Name":"db","containers":["demo"]}]});
        assert!(!merge_warm_rows(
            &mut data,
            vec![json!({"ID":id,"Names":"demo","State":"exited"})]
        ));
        assert_eq!(data["containers"][0]["started_at"], "started");
        assert_eq!(data["containers"][0]["image_id"], image);
        assert_eq!(data["containers"][0]["mounts"][0]["Name"], "db");
        assert!(data["containers"][0]["metrics"]["CPUPerc"].is_null());
        assert_eq!(data["volumes"][0]["containers"], json!(["demo"]));
        assert!(merge_warm_rows(
            &mut data,
            vec![json!({"ID":"c".repeat(64),"Names":"new","State":"running"})]
        ));
        assert_eq!(data["inventory_pending"], true);
        assert_eq!(data["volumes"][0]["containers"], json!([]));
    }
    fn inventory() -> Value {
        json!({"vm":{"running":true,"cpus":4,"memory_mib":4096},"error":null,"containers":[{"ID":"a".repeat(64),"Names":"demo-1","project":"p'; touch /tmp/bad","State":"exited","metrics":{"CPUPerc":"2.34%","MemUsage":"12MiB / 4GiB"}}],"images":[],"volumes":[]})
    }
    #[test]
    fn units_and_resource_totals() {
        assert_eq!(bytes_value(" 48.3MB "), Some(48_300_000));
        assert_eq!(bytes_value("4.33GiB"), Some((4.33 * 1073741824.) as u64));
        assert_eq!(bytes_value("-3MiB"), None);
        assert_eq!(bytes_value("5evil"), None);
        let mut v = inventory();
        add_resources(&mut v);
        assert_eq!(v["resources"]["cpu_capacity_percent"], 400);
        assert_eq!(v["resources"]["memory_used_bytes"], 12582912);
    }
    #[test]
    fn failed_full_refresh_preserves_quick_and_previous_inventory() {
        let mut previous = inventory();
        previous["updated_at"] = json!(123);
        previous["metrics_ready"] = json!(true);
        previous["images"] = json!([{"ID":"image"}]);
        previous["volumes"] = json!([{"Name":"db"}]);
        let mut failed = json!({"containers":[],"images":[],"volumes":[],"vm":{"running":true,"memory_used_bytes":5},"inventory_pending":true});
        preserve_inventory(&mut failed, &previous);
        assert_eq!(failed["containers"], previous["containers"]);
        assert_eq!(failed["images"], previous["images"]);
        assert_eq!(failed["volumes"], previous["volumes"]);
        assert_eq!(failed["updated_at"], 123);
        assert_eq!(failed["vm"]["memory_used_bytes"], 5);
        assert_eq!(failed["inventory_pending"], false);
    }
    #[test]
    fn project_names_never_become_arguments_and_members_must_match() {
        let v = inventory();
        let p = json!({"kind":"project","id":"p'; touch /tmp/bad","action":"stop"});
        assert_eq!(select_action(&v, &p).unwrap().0, vec!["a".repeat(64)]);
        let mut p = p;
        p["action"] = json!("delete");
        p["confirm"] = p["id"].clone();
        p["container_ids"] = json!([]);
        assert!(select_action(&v, &p).is_err());
        p["container_ids"] = json!(["a".repeat(64)]);
        assert!(select_action(&v, &p).is_ok());
    }
    #[test]
    fn delete_requires_stopped_and_confirmation() {
        let mut v = inventory();
        let mut p = json!({"kind":"container","id":"a".repeat(64),"action":"delete"});
        assert!(select_action(&v, &p).is_err());
        p["confirm"] = json!("demo-1");
        assert!(select_action(&v, &p).is_ok());
        v["containers"][0]["State"] = json!("running");
        assert!(select_action(&v, &p).is_err());
    }
    #[test]
    fn volumes_in_use_and_invalid_paths_are_rejected() {
        let mut v = inventory();
        v["volumes"] = json!([{"Name":"db","containers":["demo-1"]}]);
        assert!(select_action(
            &v,
            &json!({"kind":"volume","id":"db","action":"delete","confirm":"db"})
        )
        .is_err());
        assert!(select_action(
            &v,
            &json!({"kind":"volume","id":"../db","action":"delete","confirm":"../db"})
        )
        .is_err());
    }
    #[test]
    fn image_alias_and_in_use_guards() {
        let mut v = inventory();
        let id = format!("sha256:{}", "b".repeat(64));
        v["images"] = json!([{"ID":id,"Repository":"demo","Tag":"latest","containers":[]}]);
        let mut p = json!({"kind":"image","id":id,"action":"delete","reference":"demo:latest","confirm":"demo:latest"});
        assert!(select_action(&v, &p).is_ok());
        p["reference"] = json!("wrong:tag");
        assert!(select_action(&v, &p).is_err());
        p["reference"] = json!("demo:latest");
        v["images"][0]["containers"] = json!(["demo-1"]);
        assert!(select_action(&v, &p).is_err());
    }
}
