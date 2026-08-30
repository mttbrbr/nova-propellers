use serde::Serialize;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::str::FromStr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const ENDPOINT_PREFIX: &str = "NOVA_BACKEND_ENDPOINT=";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStatus {
    endpoint: Option<String>,
    ready: bool,
    error: Option<String>,
}

#[derive(Default)]
struct BackendManager {
    status: Mutex<BackendStatus>,
    child: Mutex<Option<CommandChild>>,
    shutting_down: AtomicBool,
}

impl BackendManager {
    fn status(&self) -> BackendStatus {
        self.status
            .lock()
            .expect("backend status lock poisoned")
            .clone()
    }

    fn update(&self, status: BackendStatus) {
        *self.status.lock().expect("backend status lock poisoned") = status;
    }

    fn stop(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
        if let Some(child) = self
            .child
            .lock()
            .expect("backend child lock poisoned")
            .take()
        {
            let _ = child.kill();
        }
    }
}

#[tauri::command]
fn backend_status(manager: tauri::State<'_, BackendManager>) -> BackendStatus {
    manager.status()
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn parse_endpoint(output: &str) -> Option<String> {
    output.lines().find_map(|line| {
        line.trim()
            .strip_prefix(ENDPOINT_PREFIX)
            .map(str::trim)
            .filter(|value| value.starts_with("http://127.0.0.1:"))
            .map(ToOwned::to_owned)
    })
}

fn endpoint_address(endpoint: &str) -> Option<SocketAddr> {
    let authority = endpoint.strip_prefix("http://")?.split('/').next()?;
    SocketAddr::from_str(authority).ok()
}

fn health_check(endpoint: &str) -> bool {
    let Some(address) = endpoint_address(endpoint) else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok()
        && response.starts_with("HTTP/1.1 200")
        && response.contains("{\"status\":\"ok\"}")
}

fn wait_until_ready(app: AppHandle, endpoint: String) {
    thread::spawn(move || {
        let deadline = Instant::now() + STARTUP_TIMEOUT;
        while Instant::now() < deadline {
            if health_check(&endpoint) {
                app.state::<BackendManager>().update(BackendStatus {
                    endpoint: Some(endpoint),
                    ready: true,
                    error: None,
                });
                show_main_window(&app);
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        app.state::<BackendManager>().update(BackendStatus {
            endpoint: None,
            ready: false,
            error: Some("The local backend did not become ready within 20 seconds.".into()),
        });
        show_main_window(&app);
    });
}

fn start_backend(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let data_dir = app.path().app_data_dir()?;
    std::fs::create_dir_all(&data_dir)?;
    let data_dir = data_dir
        .to_str()
        .ok_or("application data path is not valid UTF-8")?;
    let command =
        app.shell()
            .sidecar("nova-backend")?
            .args(["--port", "0", "--data-dir", data_dir]);
    let (mut events, child) = command.spawn()?;
    app.state::<BackendManager>()
        .child
        .lock()
        .expect("backend child lock poisoned")
        .replace(child);

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut output_buffer = String::new();
        let mut stderr_tail = String::new();
        let mut readiness_started = false;
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    output_buffer.push_str(&String::from_utf8_lossy(&bytes));
                    if !readiness_started {
                        if let Some(endpoint) = parse_endpoint(&output_buffer) {
                            readiness_started = true;
                            wait_until_ready(handle.clone(), endpoint);
                        }
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    stderr_tail.push_str(&String::from_utf8_lossy(&bytes));
                    if stderr_tail.len() > 2000 {
                        stderr_tail.drain(..stderr_tail.len() - 2000);
                    }
                }
                CommandEvent::Error(message) => {
                    if !handle
                        .state::<BackendManager>()
                        .shutting_down
                        .load(Ordering::SeqCst)
                    {
                        handle.state::<BackendManager>().update(BackendStatus {
                            endpoint: None,
                            ready: false,
                            error: Some(format!("Local backend error: {message}")),
                        });
                        show_main_window(&handle);
                    }
                }
                CommandEvent::Terminated(payload) => {
                    if !handle
                        .state::<BackendManager>()
                        .shutting_down
                        .load(Ordering::SeqCst)
                    {
                        let detail = stderr_tail.trim();
                        let suffix = if detail.is_empty() {
                            String::new()
                        } else {
                            format!(" Last output: {detail}")
                        };
                        handle.state::<BackendManager>().update(BackendStatus {
                            endpoint: None,
                            ready: false,
                            error: Some(format!(
                                "The local backend stopped unexpectedly (code {:?}).{}",
                                payload.code, suffix
                            )),
                        });
                        show_main_window(&handle);
                    }
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendManager::default())
        .invoke_handler(tauri::generate_handler![backend_status])
        .setup(|app| {
            if let Err(error) = start_backend(app.handle()) {
                app.state::<BackendManager>().update(BackendStatus {
                    endpoint: None,
                    ready: false,
                    error: Some(format!("Unable to start the local backend: {error}")),
                });
                show_main_window(app.handle());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Nova desktop");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            handle.state::<BackendManager>().stop();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_only_loopback_endpoint() {
        assert_eq!(
            parse_endpoint("noise\nNOVA_BACKEND_ENDPOINT=http://127.0.0.1:43125/api\n"),
            Some("http://127.0.0.1:43125/api".into())
        );
        assert_eq!(
            parse_endpoint("NOVA_BACKEND_ENDPOINT=http://0.0.0.0:8000/api"),
            None
        );
    }

    #[test]
    fn extracts_backend_socket_address() {
        assert_eq!(
            endpoint_address("http://127.0.0.1:43125/api"),
            Some(SocketAddr::from(([127, 0, 0, 1], 43125)))
        );
        assert_eq!(endpoint_address("not-an-endpoint"), None);
    }
}
