use serde_json::Value;
use std::{
    io::{BufRead, BufReader},
    net::TcpListener,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};
use tauri::{Emitter, Manager, State};

struct Connection {
    child: Child,
    url: String,
    token: String,
}

#[derive(Default)]
struct Backend {
    connection: Mutex<Option<Connection>>,
    startup: tokio::sync::Mutex<()>,
}

fn hidden(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command
}

fn resources(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf, PathBuf), String> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let (backend, python_root, uv) = if cfg!(debug_assertions) {
        (
            manifest.parent().unwrap().join("backend"),
            manifest.join("python"),
            manifest.join("binaries").join(format!(
                "index-studio-uv-{}{}",
                env!("STUDIO_TARGET"),
                std::env::consts::EXE_SUFFIX
            )),
        )
    } else {
        let root = app.path().resource_dir().map_err(|e| e.to_string())?;
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        (
            root.join("backend"),
            root.join("python"),
            exe.parent()
                .unwrap()
                .join(format!("index-studio-uv{}", std::env::consts::EXE_SUFFIX)),
        )
    };
    let runtime: Value = serde_json::from_str(
        &std::fs::read_to_string(python_root.join("runtime.json"))
            .map_err(|_| "缺少内嵌 Python。开发环境请先运行 npm run prepare:sidecar")?,
    )
    .map_err(|e| e.to_string())?;
    let interpreter = python_root
        .join(runtime["directory"].as_str().ok_or("运行时清单无效")?)
        .join(if cfg!(windows) {
            "python.exe"
        } else {
            "bin/python3.12"
        });
    if !interpreter.exists() || !uv.exists() {
        return Err("内嵌运行时不完整，请重新安装应用或运行 npm run prepare:sidecar".into());
    }
    Ok((backend, interpreter, uv))
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(Duration::from_secs(3))
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn backend_start(app: tauri::AppHandle, state: State<'_, Backend>) -> Result<Value, String> {
    let _startup = state.startup.lock().await;
    let existing = {
        let mut guard = state.connection.lock().map_err(|e| e.to_string())?;
        if let Some(connection) = guard.as_mut() {
            if connection
                .child
                .try_wait()
                .map_err(|e| e.to_string())?
                .is_none()
            {
                Some((connection.url.clone(), connection.token.clone()))
            } else {
                *guard = None;
                None
            }
        } else {
            None
        }
    };
    if let Some((url, token)) = existing {
        return client()?
            .get(format!("{url}/status"))
            .header("x-studio-token", token)
            .send()
            .await
            .map_err(|e| e.to_string())?
            .json()
            .await
            .map_err(|e| e.to_string());
    }
    let (backend, interpreter, uv) = resources(&app)?;
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;
    let environment = data_dir.join("environment-py312");
    let _ = app.emit("bootstrap-log", "正在准备应用专属 Python 环境…");
    let uv_for_setup = uv.clone();
    let environment_for_setup = environment.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let output = hidden(
            Command::new(uv_for_setup)
                .args([
                    "venv",
                    "--allow-existing",
                    "--system-site-packages",
                    "--no-python-downloads",
                    "--python",
                ])
                .arg(interpreter)
                .arg(environment_for_setup),
        )
        .output()
        .map_err(|e| e.to_string())?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).into_owned());
        }
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())??;
    let python = environment.join(if cfg!(windows) {
        "Scripts/python.exe"
    } else {
        "bin/python"
    });
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    drop(listener);
    let token = uuid::Uuid::new_v4().to_string();
    let url = format!("http://127.0.0.1:{port}");
    let mut child = hidden(
        Command::new(python)
            .arg(backend.join("main.py"))
            .arg("--data-dir")
            .arg(&data_dir)
            .arg("--port")
            .arg(port.to_string())
            .arg("--parent-pid")
            .arg(std::process::id().to_string())
            .env("INDEX_STUDIO_CONTROL_TOKEN", &token)
            .env("INDEX_STUDIO_UV", uv)
            .env("INDEX_STUDIO_WATCH_STDIN", "1")
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            .env("HF_HUB_OFFLINE", "1")
            .current_dir(&data_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped()),
    )
    .spawn()
    .map_err(|e| e.to_string())?;
    if let Some(stderr) = child.stderr.take() {
        let handle = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let _ = handle.emit("bootstrap-log", line);
            }
        });
    }
    *state.connection.lock().map_err(|e| e.to_string())? = Some(Connection {
        child,
        url: url.clone(),
        token: token.clone(),
    });
    let http = client()?;
    for _ in 0..120 {
        if let Ok(response) = http
            .get(format!("{url}/status"))
            .header("x-studio-token", &token)
            .send()
            .await
        {
            if response.status().is_success() {
                return response.json().await.map_err(|e| e.to_string());
            }
        }
        {
            let mut guard = state.connection.lock().map_err(|e| e.to_string())?;
            if let Some(connection) = guard.as_mut() {
                if let Some(exit) = connection.child.try_wait().map_err(|e| e.to_string())? {
                    return Err(format!("本地服务提前退出 ({exit})，请查看启动日志"));
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    // 关闭 stdin 会触发子进程清理，重试时不会留下旧控制服务。
    state.connection.lock().map_err(|e| e.to_string())?.take();
    Err("本地服务启动超时，请查看启动日志后重试".into())
}

#[tauri::command]
async fn backend_request(
    state: State<'_, Backend>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    let allowed = matches!(
        (method.as_str(), path.as_str()),
        ("GET", "/status")
            | ("PUT", "/settings")
            | ("POST", "/runtime/install")
            | ("POST", "/download")
            | ("POST", "/download/pause")
            | ("POST", "/deploy/start")
            | ("POST", "/deploy/stop")
            | ("POST", "/translate")
            | ("POST", "/translate/cancel")
    );
    if !allowed {
        return Err("不支持的本地操作".into());
    }
    let (url, token) = {
        let guard = state.connection.lock().map_err(|e| e.to_string())?;
        let connection = guard.as_ref().ok_or("本地服务尚未启动")?;
        (connection.url.clone(), connection.token.clone())
    };
    let mut request = client()?
        .request(
            method.parse().map_err(|_| "无效的 HTTP 方法")?,
            format!("{url}{path}"),
        )
        .header("x-studio-token", token);
    if let Some(value) = body {
        request = request.json(&value);
    }
    let response = request
        .send()
        .await
        .map_err(|e| format!("本地服务连接失败：{e}"))?;
    let status = response.status();
    let value: Value = response.json().await.map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(value["detail"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| format!("请求失败 ({status})：{value}")));
    }
    Ok(value)
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Backend::default())
        .invoke_handler(tauri::generate_handler![backend_start, backend_request])
        .build(tauri::generate_context!())
        .expect("无法创建 Index Translate Studio")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Ok(mut connection) = app.state::<Backend>().connection.lock() {
                    connection.take();
                }
            }
        });
}
