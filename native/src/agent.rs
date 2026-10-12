//! Userdir HTTP bridge. Public TLS remains on the university's PHP hosting.
use crate::{atomic, output, read_json, Kit, Result};
use serde_json::{json, Value};
use std::{
    env, fs,
    io::{Cursor, Read},
    os::unix::{
        ffi::OsStrExt,
        fs::{OpenOptionsExt, PermissionsExt},
        process::CommandExt,
    },
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};
use tiny_http::{Header, Request, Response, Server, StatusCode};

const MAX_BODY: usize = 8 * 1024 * 1024;
const MAX_RESPONSE: usize = 16 * 1024 * 1024;
const HOP: &[&str] = &[
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "expect",
];
const MARKER: &str = "// helios-container managed web gateway";
const ACCESS_MARKER: &str = "# helios-container managed web methods";
const OWNER_PREFIX: &str = "[helios-container base:";
const PHP: &str = include_str!("../../gateway.php");
const ACCESS: &str = include_str!("../../gateway.htaccess");
fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("Некорректное поле {key}").into())
}
fn constant(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.bytes().zip(b.bytes()).fold(0u8, |n, (a, b)| n | (a ^ b)) == 0
}
fn random() -> Result<String> {
    let mut bytes = [0u8; 32];
    fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}
pub fn username() -> Result<String> {
    Ok(output(Command::new("id").arg("-un"))?.trim().into())
}
pub fn owned_listener(port: u16) -> bool {
    owned_ports().contains(&port)
}
fn owned_ports() -> std::collections::BTreeSet<u16> {
    let Ok(user) = username() else {
        return Default::default();
    };
    let Ok(list) = output(Command::new("sockstat").args(["-4", "-l", "-P", "tcp"])) else {
        return Default::default();
    };
    list.lines()
        .skip(1)
        .filter_map(|line| {
            let f = line.split_whitespace().collect::<Vec<_>>();
            if f.len() < 6 || f[0] != user {
                return None;
            }
            let (address, port) = f[5].rsplit_once(':')?;
            if !["127.0.0.1", "*", "0.0.0.0"].contains(&address) {
                return None;
            }
            port.parse().ok()
        })
        .collect()
}
fn validate_state(state: &Value) -> Result<()> {
    for key in ["bridge_key", "admin_key"] {
        let value = text(state, key)?;
        if value.len() != 64 || !value.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("Повреждены ключи шлюза".into());
        }
    }
    if !(1024..=65535).contains(&state["agent_port"].as_u64().unwrap_or(0)) {
        return Err("Некорректный порт агента".into());
    }
    let routes = state["routes"].as_array().ok_or("Нет маршрутов")?;
    if routes.len() > 8 {
        return Err("Слишком много маршрутов".into());
    }
    for route in routes {
        let kind = route["kind"].as_str().unwrap_or("");
        let port = route["port"].as_u64().unwrap_or(0);
        if !["vm", "host"].contains(&kind)
            || !(1..=65535).contains(&port)
            || (kind == "host" && port < 1024)
            || !(1024..=65535).contains(&route["target"].as_u64().unwrap_or(0))
        {
            return Err("Некорректный маршрут".into());
        }
    }
    Ok(())
}
fn native_command_matches(actual: &str, expected: &str) -> bool {
    let command = actual.trim();
    command == expected
        || command
            .strip_suffix(" (helios-container-na)")
            .is_some_and(|command| command == expected)
}
fn process_pid(base: &Path) -> Option<u32> {
    let pid: u32 = fs::read_to_string(base.join("web.pid"))
        .ok()?
        .trim()
        .parse()
        .ok()?;
    let list = output(Command::new("ps").args([
        "-ww",
        "-p",
        &pid.to_string(),
        "-o",
        "uid=",
        "-o",
        "command=",
    ]))
    .ok()?;
    let (uid, cmd) = list.trim().split_once(char::is_whitespace)?;
    let native_command = format!(
        "{} --base {} _agent",
        base.join("helios-container-native").to_str()?,
        base.to_str()?
    );
    if uid.parse::<u32>().ok()? == unsafe { libc::getuid() }
        && (native_command_matches(cmd, &native_command)
            || (cmd.contains(base.join("gateway.py").to_str()?) && cmd.contains("serve")))
    {
        Some(pid)
    } else {
        None
    }
}
pub fn stop(base: &Path) -> Result<()> {
    if let Some(pid) = process_pid(base) {
        unsafe {
            libc::kill(pid as i32, libc::SIGTERM);
        }
        for _ in 0..50 {
            if process_pid(base).is_none() {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(100));
        }
        return Err("Агент ещё останавливается".into());
    }
    Ok(())
}
pub fn ensure(base: &Path) -> Result<()> {
    let state = read_json(&base.join("web.json"))?;
    validate_state(&state)?;
    if let Some(pid) = process_pid(base) {
        let command =
            output(Command::new("ps").args(["-ww", "-p", &pid.to_string(), "-o", "command="]))?;
        if command.contains(&base.join("gateway.py").display().to_string()) {
            stop(base)?;
        }
    }
    if process_pid(base).is_none() {
        let log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(base.join("web.log"))?;
        let mut command = Command::new(base.join("helios-container-native"));
        command
            .arg("--base")
            .arg(base)
            .arg("_agent")
            .stdin(Stdio::null())
            .stdout(log.try_clone()?)
            .stderr(log);
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let child = command.spawn()?;
        atomic(
            &base.join("web.pid"),
            child.id().to_string().as_bytes(),
            0o600,
        )?;
    }
    let client: ureq::Agent = ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(1)))
        .proxy(None)
        .build()
        .into();
    let url = format!("http://127.0.0.1:{}/_health", state["agent_port"]);
    for _ in 0..50 {
        if let Ok(mut reply) = client
            .get(&url)
            .header("X-HC-Bridge", text(&state, "bridge_key")?)
            .call()
        {
            if reply.body_mut().read_to_string().unwrap_or_default() == "helios-container gateway" {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(200));
    }
    Err("Шлюз не запустился. Проверьте web.log".into())
}
fn ownership(base: &Path) -> Result<String> {
    let base = base.canonicalize()?;
    let encoded: String = base
        .as_os_str()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(format!("{OWNER_PREFIX}{encoded}]"))
}
fn foreign_ownership(content: &str, owner: &str) -> bool {
    content
        .match_indices(OWNER_PREFIX)
        .any(|(offset, _)| !content[offset..].starts_with(owner))
}
fn safe_file(path: &Path, marker: &str, owner: &str) -> Result<()> {
    if !regular_file(path)? {
        return Ok(());
    }
    let content = fs::read_to_string(path)?;
    if foreign_ownership(&content, owner) {
        return Err(format!(
            "Файл {} принадлежит другой установке. Существующие данные сохранены",
            path.display()
        )
        .into());
    }
    if !content.contains(marker) {
        return Err(format!(
            "Файл {} не принадлежит kit. Существующие данные сохранены",
            path.display()
        )
        .into());
    }
    Ok(())
}
fn regular_file(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() => Ok(true),
        Ok(_) => Err(format!(
            "Ожидался обычный файл: {}. Существующие данные сохранены",
            path.display()
        )
        .into()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(format!("Не удалось проверить {}: {error}", path.display()).into()),
    }
}
fn web_root() -> Result<PathBuf> {
    let home = PathBuf::from(env::var("HOME")?);
    let public = home.join("public_html");
    let root = public.join("helios-container");
    crate::install::no_links(&root)?;
    for path in [&home, &public, &root] {
        match fs::symlink_metadata(path) {
            Ok(metadata) if metadata.is_dir() => {}
            Ok(_) => return Err(format!("Ожидался каталог: {}", path.display()).into()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound && path != &home => {}
            Err(error) => {
                return Err(format!("Не удалось проверить {}: {error}", path.display()).into())
            }
        }
    }
    Ok(root)
}
fn web_permissions(root: &Path) -> Result<()> {
    let public = root.parent().ok_or("Нет каталога public_html")?;
    let home = public.parent().ok_or("Нет домашнего каталога")?;
    let mut errors = Vec::new();
    for (path, required, suggested) in [
        (home, 0o001, "711"),
        (public, 0o005, "755"),
        (root, 0o005, "755"),
    ] {
        match fs::metadata(path) {
            Ok(metadata) => {
                let mode = metadata.permissions().mode() & 0o7777;
                if mode & required != required {
                    errors.push(format!(
                        "{}: права {mode:04o}, хостингу нужны {}. Выполните: chmod {suggested} {}",
                        path.display(),
                        if required == 0o001 {
                            "проход по каталогу"
                        } else {
                            "чтение и проход по каталогу"
                        },
                        crate::quote(&path.to_string_lossy())
                    ));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(
                    format!("Не удалось проверить права {}: {error}", path.display()).into(),
                )
            }
        }
    }
    if !errors.is_empty() {
        return Err(format!("Хостинг не сможет открыть PHP-шлюз:\n{}", errors.join("\n")).into());
    }
    Ok(())
}
fn create_web_directory(path: &Path) -> Result<()> {
    if !path.exists() {
        fs::create_dir(path)?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o755))?;
    }
    Ok(())
}
pub fn remove(base: &Path) -> Result<()> {
    let root = web_root()?;
    let owner = ownership(base)?;
    let state_path = base.join("web.json");
    let has_state = regular_file(&state_path)?;
    if has_state && text(&read_json(&state_path)?, "directory")? != root.to_string_lossy() {
        return Err("Неизвестный каталог шлюза".into());
    }
    let index = root.join("index.php");
    let access = root.join(".htaccess");
    safe_file(&index, MARKER, &owner)?;
    safe_file(&access, ACCESS_MARKER, &owner)?;
    let owned_root = has_state || index.exists() || access.exists();
    let files = [
        index,
        access,
        state_path,
        base.join("web.pid"),
        base.join("web.log"),
    ];
    for path in &files {
        regular_file(path)?;
    }
    stop(base)?;
    for path in &files {
        if path.exists() {
            fs::remove_file(path)?;
        }
    }
    if owned_root && root.exists() && fs::read_dir(&root)?.next().is_none() {
        fs::remove_dir(root)?;
    }
    println!("HTTP-шлюз удалён. Frontend и VM сохранены");
    Ok(())
}
pub fn remove_owned(base: &Path) -> Result<()> {
    let root = PathBuf::from(env::var("HOME")?).join("public_html/helios-container");
    let owner = ownership(base)?;
    let has_state = fs::symlink_metadata(base.join("web.json")).is_ok();
    let has_gateway = crate::install::no_links(&root).is_ok()
        && [
            (root.join("index.php"), MARKER),
            (root.join(".htaccess"), ACCESS_MARKER),
        ]
        .iter()
        .any(|(path, marker)| {
            fs::symlink_metadata(path).is_ok_and(|metadata| metadata.is_file())
                && fs::read_to_string(path)
                    .is_ok_and(|content| content.contains(marker) && content.contains(&owner))
        });
    if has_state || has_gateway {
        remove(base)?;
    } else {
        stop(base)?;
    }
    Ok(())
}
pub fn manage(kit: &Kit, args: &[String]) -> Result<()> {
    if args.len() != 1 {
        return Err("web install|info|start|stop|remove".into());
    }
    let base = &kit.base;
    if args[0] == "stop" {
        return stop(base);
    }
    if args[0] == "install" {
        let root = web_root()?;
        web_permissions(&root)?;
        let public = root.parent().ok_or("Нет каталога public_html")?;
        let state = if base.join("web.json").exists() {
            read_json(&base.join("web.json"))?
        } else {
            if root.exists() && fs::read_dir(&root)?.next().is_some() {
                return Err("Каталог public_html/helios-container уже занят".into());
            }
            let user = username()?;
            if !user
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            {
                return Err("Неожиданное имя пользователя".into());
            }
            let url = format!("https://se.ifmo.ru/~{user}/helios-container/");
            create_web_directory(public)?;
            create_web_directory(&root)?;
            let nonce = random()?;
            let probe = root.join(format!("probe-{nonce}.php"));
            atomic(&probe, format!("<?php echo '{nonce}';").as_bytes(), 0o644)?;
            let probe_url = format!("{url}{}", probe.file_name().unwrap().to_string_lossy());
            let result = output(
                Command::new("curl")
                    .args([
                        "--proto",
                        "=https",
                        "-fsS",
                        "--connect-timeout",
                        "10",
                        "--max-time",
                        "20",
                    ])
                    .arg(&probe_url),
            );
            fs::remove_file(&probe).map_err(|error| {
                format!(
                    "Не удалось удалить проверочный файл {}: {error}",
                    probe.display()
                )
            })?;
            if result.map_err(|error| format!("Проверка PHP-хостинга {probe_url}: {error}"))?
                != nonce
            {
                return Err(format!(
                    "Хостинг не выполняет PHP или вернул неожиданный ответ: {probe_url}"
                )
                .into());
            }
            let port = std::net::TcpListener::bind(("127.0.0.1", 0))?
                .local_addr()?
                .port();
            json!({"url":url,"directory":root,"agent_port":port,"admin_key":random()?,"bridge_key":random()?,"routes":[]})
        };
        if text(&state, "directory")? != root.to_string_lossy() {
            return Err("Неизвестный каталог шлюза".into());
        }
        let owner = ownership(base)?;
        safe_file(&root.join("index.php"), MARKER, &owner)?;
        safe_file(&root.join(".htaccess"), ACCESS_MARKER, &owner)?;
        create_web_directory(public)?;
        create_web_directory(&root)?;
        let php = PHP
            .replace(MARKER, &format!("{MARKER} {owner}"))
            .replace("__HC_PORT__", &state["agent_port"].to_string())
            .replace("__HC_BRIDGE__", text(&state, "bridge_key")?);
        let access = ACCESS.replace(ACCESS_MARKER, &format!("{ACCESS_MARKER} {owner}"));
        atomic(&root.join("index.php"), php.as_bytes(), 0o644)?;
        atomic(&root.join(".htaccess"), access.as_bytes(), 0o644)?;
        atomic(
            &base.join("web.json"),
            serde_json::to_vec_pretty(&state)?.as_slice(),
            0o600,
        )?;
        ensure(base)?;
    } else if args[0] == "start" {
        ensure(base)?;
    } else if args[0] == "remove" {
        return remove(base);
    } else if args[0] != "info" {
        return Err("Неизвестная команда web".into());
    }
    let state = read_json(&base.join("web.json"))?;
    println!(
        "Страница: {}\nУправление (приватная ссылка): {}#key={}\nАгент: {}",
        text(&state, "url")?,
        text(&state, "url")?,
        text(&state, "admin_key")?,
        if process_pid(base).is_some() {
            "работает"
        } else {
            "остановлен"
        }
    );
    Ok(())
}
struct State {
    base: PathBuf,
    config: Mutex<Value>,
    writer: Mutex<()>,
    dashboard: Arc<crate::dashboard::Dashboard>,
    client: ureq::Agent,
}
fn header(req: &Request, name: &'static str) -> String {
    req.headers()
        .iter()
        .find(|h| h.field.equiv(name))
        .map(|h| h.value.as_str().to_owned())
        .unwrap_or_default()
}
fn json_reply(req: Request, code: u16, value: Value) {
    let data = serde_json::to_vec(&value).unwrap_or_default();
    let mut response = Response::from_data(data).with_status_code(code);
    for (k, v) in [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
    ] {
        response.add_header(Header::from_bytes(k, v).unwrap());
    }
    let _ = req.respond(response);
}
fn body(req: &mut Request, max: usize) -> Result<Vec<u8>> {
    if req.body_length().is_some_and(|n| n > max) {
        return Err("Слишком большой запрос".into());
    }
    let mut b = Vec::new();
    req.as_reader().take(max as u64 + 1).read_to_end(&mut b)?;
    if b.len() > max {
        return Err("Слишком большой запрос".into());
    }
    Ok(b)
}
pub fn parse_ports(s: &str) -> Result<Vec<Value>> {
    let mut routes = Vec::new();
    for word in s
        .split(|c: char| c.is_whitespace() || c == ',' || c == ';')
        .filter(|s| !s.is_empty())
    {
        let (kind, n) = word
            .strip_prefix("host:")
            .map(|n| ("host", n))
            .unwrap_or(("vm", word));
        if !n.bytes().all(|b| b.is_ascii_digit()) {
            return Err("Введите порты: 8080, 8081, host:3000".into());
        }
        let port = crate::port(n, if kind == "host" { 1024 } else { 1 })?;
        let route = json!({"kind":kind,"port":port});
        if !routes.contains(&route) {
            routes.push(route);
        }
    }
    if routes.len() > 8 {
        return Err("Можно опубликовать до 8 портов".into());
    }
    Ok(routes)
}
fn routes_json(state: &Value) -> Value {
    json!({"ports":state["routes"].as_array().unwrap().iter().map(|r|format!("{}{}",if r["kind"]=="host"{"host:"}else{""},r["port"])).collect::<Vec<_>>().join(", "),"routes":state["routes"].as_array().unwrap().iter().map(|r|json!({"kind":r["kind"],"port":r["port"],"path":format!("/{}/{}/",r["kind"].as_str().unwrap(),r["port"])})).collect::<Vec<_>>()})
}
fn query<'a>(url: &'a str, key: &str) -> &'a str {
    url.split_once('?')
        .and_then(|(_, q)| {
            q.split('&')
                .find_map(|p| p.split_once('=').filter(|(k, _)| *k == key).map(|(_, v)| v))
        })
        .unwrap_or("")
}
fn handle(mut req: Request, state: &State) {
    let url = req.url().to_owned();
    let path = url.split('?').next().unwrap_or("");
    let method = req.method().as_str().to_string();
    let config = state.config.lock().unwrap().clone();
    if !constant(
        &header(&req, "X-HC-Bridge"),
        config["bridge_key"].as_str().unwrap_or(""),
    ) {
        json_reply(req, 403, json!({"error":"Только через HTTPS-шлюз"}));
        return;
    }
    if path == "/_health" {
        let _ = req.respond(Response::from_string("helios-container gateway"));
        return;
    }
    if ["/_dashboard", "/_logs", "/_action", "/_config"].contains(&path) {
        if !constant(
            &header(&req, "X-HC-Admin"),
            config["admin_key"].as_str().unwrap_or(""),
        ) {
            json_reply(
                req,
                401,
                json!({"error":"Откройте приватную ссылку из helios-container web info"}),
            );
            return;
        }
        let result = (|| -> Result<(u16, Value)> {
            match path {
                "/_dashboard" | "/_logs" => {
                    if method != "GET" {
                        return Ok((405, json!({"error":"Используйте GET"})));
                    }
                    if path == "/_logs" {
                        return Ok((
                            200,
                            state.dashboard.logs(
                                query(&url, "id"),
                                if query(&url, "tail").is_empty() {
                                    "200"
                                } else {
                                    query(&url, "tail")
                                },
                            )?,
                        ));
                    }
                    let mut data = state.dashboard.snapshot();
                    let listeners = owned_ports();
                    data["routes"]=json!(config["routes"].as_array().ok_or("Нет маршрутов")?.iter().map(|r|json!({"kind":r["kind"],"port":r["port"],"path":format!("/{}/{}/",r["kind"].as_str().unwrap_or(""),r["port"]),"listening":listeners.contains(&(r["target"].as_u64().unwrap_or(0) as u16))})).collect::<Vec<_>>());
                    Ok((200, data))
                }
                "/_action" => {
                    if method == "GET" {
                        return Ok((200, state.dashboard.job(query(&url, "id"))?));
                    }
                    if method != "POST" {
                        return Ok((405, json!({"error":"Используйте GET или POST"})));
                    }
                    if req.body_length().is_some_and(|n| n == 0 || n > 4096) {
                        return Ok((413, json!({"error":"Слишком большой запрос"})));
                    }
                    Ok((
                        202,
                        state
                            .dashboard
                            .action(serde_json::from_slice(&body(&mut req, 4096)?)?)?,
                    ))
                }
                _ => {
                    if method == "POST" {
                        if req.body_length().is_some_and(|n| n == 0 || n > 4096) {
                            return Ok((413, json!({"error":"Слишком большой запрос"})));
                        }
                        let payload: Value = serde_json::from_slice(&body(&mut req, 4096)?)?;
                        let mut routes =
                            parse_ports(payload["ports"].as_str().ok_or("Нужны порты")?)?;
                        let _writer = state.writer.lock().unwrap();
                        let mut kit = Kit::load(state.base.clone())?;
                        if routes.iter().any(|r| r["kind"] == "vm") && kit.pid().is_none() {
                            return Err("VM остановлена. Сначала запустите VM".into());
                        }
                        for route in &mut routes {
                            let port = route["port"].as_u64().unwrap() as u16;
                            let target = if route["kind"] == "host" {
                                if !owned_listener(port) {
                                    return Err(
                                        "Порт не слушает процесс вашего пользователя".into()
                                    );
                                }
                                port
                            } else {
                                kit.forward(port, 0)?
                            };
                            route["target"] = json!(target);
                        }
                        let mut updated = state.config.lock().unwrap().clone();
                        updated["routes"] = json!(routes);
                        atomic(
                            &state.base.join("web.json"),
                            serde_json::to_vec_pretty(&updated)?.as_slice(),
                            0o600,
                        )?;
                        *state.config.lock().unwrap() = updated.clone();
                        Ok((200, routes_json(&updated)))
                    } else if method == "GET" {
                        Ok((200, routes_json(&config)))
                    } else {
                        Ok((405, json!({"error":"Используйте GET или POST"})))
                    }
                }
            }
        })();
        match result {
            Ok((code, data)) => json_reply(req, code, data),
            Err(_) => json_reply(
                req,
                400,
                json!({"error":"Некорректная операция. Обновите состояние и проверьте параметры"}),
            ),
        }
        return;
    }
    if !["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"].contains(&method.as_str()) {
        json_reply(req, 405, json!({"error":"HTTP-метод не поддерживается"}));
        return;
    }
    if !header(&req, "Transfer-Encoding").is_empty() {
        json_reply(
            req,
            400,
            json!({"error":"Chunked-загрузка не поддерживается"}),
        );
        return;
    }
    let pieces = path.splitn(4, '/').collect::<Vec<_>>();
    if pieces.len() < 3 {
        json_reply(req, 404, json!({"error":"Порт не опубликован"}));
        return;
    }
    let selected = config["routes"].as_array().and_then(|r| {
        r.iter().find(|r| {
            r["kind"].as_str() == Some(pieces[1])
                && r["port"].as_u64().map(|n| n.to_string()) == Some(pieces[2].to_string())
        })
    });
    let Some(route) = selected else {
        json_reply(req, 404, json!({"error":"Порт не опубликован"}));
        return;
    };
    let target = route["target"].as_u64().unwrap_or(0) as u16;
    let valid = if route["kind"] == "host" {
        owned_listener(target)
    } else {
        Kit::load(state.base.clone()).is_ok_and(|kit| {
            kit.pid().is_some()
                && kit.c["forwards"].as_array().is_some_and(|maps| {
                    maps.iter()
                        .any(|m| m["guest"] == route["port"] && m["host"] == route["target"])
                })
        })
    };
    if !valid {
        json_reply(
            req,
            503,
            json!({"error":"Backend или VM остановлен, либо проброс изменён"}),
        );
        return;
    }
    if req.body_length().is_some_and(|n| n > MAX_BODY) {
        return json_reply(req, 413, json!({"error":"Запрос больше 8 МиБ"}));
    }
    type GatewayResponse = (u16, Vec<u8>, Vec<(String, String)>, Option<usize>);
    let result = (|| -> Result<GatewayResponse> {
        let body = body(&mut req, MAX_BODY)?;
        let suffix = format!(
            "/{}{}",
            pieces.get(3).unwrap_or(&""),
            url.split_once('?')
                .map(|(_, q)| format!("?{q}"))
                .unwrap_or_default()
        );
        let destination = format!("http://127.0.0.1:{target}{suffix}");
        let connection = header(&req, "Connection").to_ascii_lowercase();
        let prefix = format!(
            "{}/{}/{}",
            header(&req, "X-HC-Prefix"),
            route["kind"].as_str().unwrap_or(""),
            route["port"]
        );
        let mut request = ureq::http::Request::builder()
            .method(method.as_str())
            .uri(&destination);
        for h in req.headers() {
            let key = h.field.as_str().as_str();
            let lower = key.to_ascii_lowercase();
            if !HOP.contains(&lower.as_str())
                && lower != "host"
                && !lower.starts_with("x-hc-")
                && !lower.starts_with("x-forwarded-")
                && !connection.split(',').any(|v| v.trim() == lower)
            {
                request = request.header(key, h.value.as_str());
            }
        }
        request = request
            .header("X-Forwarded-Proto", "https")
            .header("X-Forwarded-Host", "se.ifmo.ru")
            .header("X-Forwarded-Prefix", &prefix);
        let mut response = state.client.run(request.body(body)?)?;
        let code = response.status().as_u16();
        let connection = response
            .headers()
            .get("Connection")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_ascii_lowercase();
        let length = response
            .headers()
            .get("Content-Length")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse().ok());
        let mut headers = Vec::new();
        for (key, value) in response.headers() {
            let key = key.as_str();
            if HOP.contains(&key) || connection.split(',').any(|v| v.trim() == key) {
                continue;
            }
            let mut value = value.to_str()?.to_string();
            if key == "location" {
                let local = format!("http://127.0.0.1:{target}");
                if value.starts_with(&(local.clone() + "/")) {
                    value = value[local.len()..].into();
                }
                if value.starts_with('/') && !value.starts_with("//") {
                    value = prefix.clone() + &value;
                }
            } else if key == "set-cookie" {
                value = value
                    .split(';')
                    .filter(|p| !p.trim().to_ascii_lowercase().starts_with("domain="))
                    .map(|p| {
                        let trimmed = p.trim();
                        if trimmed.to_ascii_lowercase().starts_with("path=/") {
                            format!(" Path={}{}", prefix, &trimmed[5..])
                        } else {
                            p.to_string()
                        }
                    })
                    .collect::<Vec<_>>()
                    .join(";");
            }
            headers.push((key.to_string(), value));
        }
        let mut data = Vec::new();
        response
            .body_mut()
            .as_reader()
            .take(MAX_RESPONSE as u64 + 1)
            .read_to_end(&mut data)?;
        if data.len() > MAX_RESPONSE {
            return Err("Ответ backend больше 16 МиБ".into());
        }
        Ok((code, data, headers, length))
    })();
    match result {
        Ok((code, data, headers, length)) => {
            let size = if method == "HEAD" {
                length.unwrap_or(0)
            } else {
                data.len()
            };
            let headers = headers
                .into_iter()
                .filter_map(|(k, v)| Header::from_bytes(k, v).ok())
                .collect();
            let response = Response::new(
                StatusCode(code),
                headers,
                Cursor::new(data),
                Some(size),
                None,
            );
            let _ = req.respond(response);
        }
        Err(_) => json_reply(
            req,
            502,
            json!({"error":"Backend или VM не отвечает. Проверьте status и логи"}),
        ),
    }
}
pub fn serve(base: PathBuf) -> Result<()> {
    let config = read_json(&base.join("web.json"))?;
    let port = config["agent_port"].as_u64().ok_or("Нет порта агента")?;
    validate_state(&config)?;
    let server = Arc::new(
        Server::http(("127.0.0.1", port as u16)).map_err(|_| "Не удалось открыть порт агента")?,
    );
    let client = ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(15)))
        .http_status_as_error(false)
        .max_redirects(0)
        .proxy(None)
        .build()
        .into();
    let state = Arc::new(State {
        dashboard: crate::dashboard::Dashboard::new(base.clone()),
        base,
        config: Mutex::new(config),
        writer: Mutex::new(()),
        client,
    });
    let mut workers = Vec::new();
    for _ in 0..8 {
        let server = server.clone();
        let state = state.clone();
        workers.push(thread::spawn(move || {
            while let Ok(req) = server.recv() {
                handle(req, &state);
            }
        }));
    }
    for worker in workers {
        let _ = worker.join();
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_pid_accepts_verified_ps_suffix_and_requires_exact_installation() {
        let base = "/tmp/student's home/kit";
        let command = format!("{base}/helios-container-native --base {base} _agent");
        assert!(native_command_matches(&command, &command));
        assert!(native_command_matches(
            &format!("{command} (helios-container-na)"),
            &command
        ));
        for unrelated in [
            command.replace("/kit", "/kit-other"),
            format!("{base}/helios-container-native --base {base}-other _agent"),
            format!("prefix {command}"),
            format!("{command} extra"),
            format!("{command} (other-process)"),
            format!("{command} (helios-container-na) extra"),
        ] {
            assert!(!native_command_matches(&unrelated, &command));
        }
    }
    #[test]
    fn ports_are_bounded_and_deduplicated() {
        assert_eq!(parse_ports("8080, 8080 host:3000").unwrap().len(), 2);
        for value in ["host:22", "0", "65536", "1; echo hi"] {
            assert!(parse_ports(value).is_err());
        }
    }
    #[test]
    fn comparison_requires_exact_key() {
        assert!(constant("abc", "abc"));
        assert!(!constant("abc", "abd"));
        assert!(!constant("abc", ""));
    }
    #[test]
    fn missing_keys_never_disable_authentication() {
        let mut state = json!({"agent_port":30000,"admin_key":"a".repeat(64),"bridge_key":"b".repeat(64),"routes":[]});
        assert!(validate_state(&state).is_ok());
        state["admin_key"] = json!("");
        assert!(validate_state(&state).is_err());
        state.as_object_mut().unwrap().remove("admin_key");
        assert!(validate_state(&state).is_err());
    }
}
