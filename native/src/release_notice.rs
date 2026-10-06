//! Non-blocking release notification; independent of Docker and VM activity.
use serde_json::{json, Value};
use std::{
    fs,
    path::PathBuf,
    process::Command,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

const REPO: &str = "RedGry/helios-container";
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn version(value: &str) -> Option<(u64, u64, u64)> {
    let parts: Vec<_> = value.trim_start_matches('v').split('.').collect();
    if parts.len() != 3
        || parts.iter().any(|p| {
            p.is_empty()
                || !p.bytes().all(|b| b.is_ascii_digit())
                || (p.len() > 1 && p.starts_with('0'))
        })
    {
        return None;
    }
    Some((
        parts[0].parse().ok()?,
        parts[1].parse().ok()?,
        parts[2].parse().ok()?,
    ))
}

fn latest() -> Result<Option<Value>> {
    let output = Command::new("curl")
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
    if !output.status.success() || output.stdout.len() > 1048600 {
        return Err("Не удалось проверить релизы".into());
    }
    let text = String::from_utf8(output.stdout)?;
    let (body, status) = text.rsplit_once('\n').ok_or("Некорректный ответ GitHub")?;
    if status == "404" {
        return Ok(None);
    }
    if status != "200" {
        return Err(format!("GitHub HTTP {status}").into());
    }
    let release: Value = serde_json::from_str(body)?;
    if release["draft"] == true || release["prerelease"] == true {
        return Ok(None);
    }
    if version(release["tag_name"].as_str().unwrap_or("")).is_none() {
        return Err("Некорректная версия релиза".into());
    }
    Ok(Some(release))
}

fn notice(current: &str, release: Option<&Value>) -> Value {
    let mut data = json!({"current_version":current,"available":false});
    let Some(release) = release else {
        return data;
    };
    if release["draft"] == true || release["prerelease"] == true {
        return data;
    }
    let tag = release["tag_name"].as_str().unwrap_or("");
    let (Some(installed), Some(candidate)) = (version(current), version(tag)) else {
        return data;
    };
    if candidate <= installed {
        return data;
    }
    let native = [
        "helios-container-freebsd-amd64",
        "helios-container-freebsd-amd64.sha256",
        "VERSION",
    ];
    let compatible = native.iter().all(|name| {
        release["assets"].as_array().is_some_and(|assets| {
            assets.iter().any(|asset| {
                asset["name"] == *name
                    && asset["browser_download_url"]
                        == format!("https://github.com/{REPO}/releases/download/{tag}/{name}")
            })
        })
    });
    data["available"] = json!(true);
    data["latest_version"] = json!(tag.trim_start_matches('v'));
    data["changelog_url"] = json!(format!("https://github.com/{REPO}/releases/tag/{tag}"));
    data["notes"] = json!(release["body"]
        .as_str()
        .unwrap_or("")
        .chars()
        .take(32768)
        .collect::<String>());
    data["compatible"] = json!(compatible);
    data
}

struct State {
    release: Option<Value>,
    due: Instant,
    checking: bool,
    error: Option<String>,
}
pub(super) struct ReleaseNotice {
    base: PathBuf,
    state: Mutex<State>,
}
impl ReleaseNotice {
    pub(super) fn new(base: PathBuf) -> Arc<Self> {
        Arc::new(Self {
            base,
            state: Mutex::new(State {
                release: None,
                due: Instant::now(),
                checking: false,
                error: None,
            }),
        })
    }
    pub(super) fn snapshot(self: &Arc<Self>) -> Value {
        let current = fs::read_to_string(self.base.join("VERSION"))
            .unwrap_or_else(|_| env!("CARGO_PKG_VERSION").to_owned());
        let mut state = self.state.lock().unwrap();
        if !state.checking && Instant::now() >= state.due {
            state.checking = true;
            let owner = Arc::clone(self);
            thread::spawn(move || owner.refresh());
        }
        let mut data = notice(current.trim(), state.release.as_ref());
        data["checking"] = json!(state.checking);
        data["error"] = json!(state.error);
        data
    }
    fn refresh(self: Arc<Self>) {
        let result = latest();
        let mut state = self.state.lock().unwrap();
        match result {
            Ok(release) => {
                state.release = release;
                state.error = None;
                state.due = Instant::now() + Duration::from_secs(3600);
            }
            // Retain a known available release during temporary GitHub failures.
            Err(error) => {
                state.error = Some(error.to_string());
                state.due = Instant::now() + Duration::from_secs(300);
            }
        }
        state.checking = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn newer_only_and_safe_release_link() {
        let release = json!({"tag_name":"v0.10.0","html_url":"javascript:bad","body":"### New Features\n- Новая панель"});
        let data = notice("0.9.0", Some(&release));
        assert_eq!(data["available"], true);
        assert_eq!(
            data["changelog_url"],
            "https://github.com/RedGry/helios-container/releases/tag/v0.10.0"
        );
        assert_eq!(notice("0.10.0", Some(&release))["available"], false);
        assert_eq!(notice("1.0.0", Some(&release))["available"], false);
    }
    #[test]
    fn no_drafts_previews_or_invalid_versions() {
        for release in [
            json!({"tag_name":"v1.0.0","draft":true}),
            json!({"tag_name":"v1.0.0","prerelease":true}),
            json!({"tag_name":"v1.0.0-beta"}),
            json!({"tag_name":"v1.0.0/evil"}),
        ] {
            assert_eq!(notice("0.1.0", Some(&release))["available"], false);
        }
        assert_eq!(
            notice("dev", Some(&json!({"tag_name":"v1.0.0"})))["available"],
            false
        );
        assert_eq!(notice("0.1.0", None)["available"], false);
    }
    #[test]
    fn bounded_notes_and_native_compatibility() {
        let mut release = json!({"tag_name":"v1.0.0","body":"я".repeat(40000),"assets":[]});
        assert_eq!(notice("0.1.0", Some(&release))["compatible"], false);
        release["assets"] = json!(["helios-container-freebsd-amd64","helios-container-freebsd-amd64.sha256","VERSION"].map(|name|json!({"name":name,"browser_download_url":format!("https://github.com/{REPO}/releases/download/v1.0.0/{name}")})));
        let data = notice("0.1.0", Some(&release));
        assert_eq!(data["compatible"], true);
        assert_eq!(data["notes"].as_str().unwrap().chars().count(), 32768);
    }
}
