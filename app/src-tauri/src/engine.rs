//! 引擎连接：先连已在运行的服务（读 api.json 并用 /api/health 确认），连不上再自己拉起 `serve`。
//!
//! - 自己拉起的进程放进 Windows 作业对象（关闭时结束整棵进程树：venv 的 python.exe 是转发器，真正的解释器是它的子进程）；
//! - 退出应用时先请求 `POST /api/shutdown` 让引擎正常退出（急停任务、断开设备），超时再强制结束；
//! - 连上的是别人起的服务时，退出不动它。
//!
//! 拉起什么（B10）：
//! - 打包版（release 构建）：随包的冻结引擎 `<资源目录>/engine/e7engine.exe`（PyInstaller onedir，见 engine/packaging/）；
//! - 开发版（debug 构建）：编译期的 `<app>/../engine` 下的 venv（`.venv/Scripts/python.exe -m e7helper.cli`）；
//! - 两种构建都可以用环境变量 `E7_ENGINE_DIR` 指定源码引擎目录（走 venv）。
//!
//! `E7_ENGINE_ARGS` 给 serve 附加参数，`E7_DATA_DIR` 换数据目录（引擎和这里都认）。

use serde::{Deserialize, Serialize};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

const START_TIMEOUT: Duration = Duration::from_secs(90);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(8);

#[derive(Serialize, Clone, Debug)]
pub struct Connection {
    pub url: String,
    pub token: Option<String>,
    /// true = 这个服务是本应用拉起的，退出时会关掉它
    pub spawned: bool,
    pub pid: u32,
}

#[derive(Deserialize)]
struct ApiInfo {
    pid: u32,
    url: String,
    token: Option<String>,
}

struct Spawned {
    child: Child,
    conn: Connection,
    /// 只为持有句柄：随 Spawned 释放时结束整棵进程树
    #[cfg(windows)]
    #[allow(dead_code)]
    job: job::Job,
}

#[derive(Default)]
pub struct EngineState {
    inner: Mutex<Option<Spawned>>,
}

fn data_dir() -> PathBuf {
    if let Ok(d) = std::env::var("E7_DATA_DIR") {
        if !d.is_empty() {
            return PathBuf::from(d);
        }
    }
    let base = std::env::var("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("."));
    base.join("e7helper")
}

/// 要拉起的引擎。
#[cfg_attr(debug_assertions, allow(dead_code))]
enum Launch {
    /// 随包的冻结引擎 exe
    Bundled(PathBuf),
    /// 源码引擎目录（venv）
    Source(PathBuf),
}

fn launch_target(resource_dir: Option<&Path>) -> Result<Launch, String> {
    if let Ok(d) = std::env::var("E7_ENGINE_DIR") {
        if !d.is_empty() {
            return Ok(Launch::Source(PathBuf::from(d)));
        }
    }
    #[cfg(debug_assertions)]
    {
        let _ = resource_dir;
        Ok(Launch::Source(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("engine")))
    }
    #[cfg(not(debug_assertions))]
    {
        let dir = resource_dir.ok_or_else(|| "找不到应用的资源目录".to_string())?;
        let exe = dir.join("engine").join("e7engine.exe");
        if !exe.is_file() {
            return Err(format!("找不到引擎 {}，请重新安装", exe.display()));
        }
        Ok(Launch::Bundled(exe))
    }
}

fn read_api_info() -> Option<ApiInfo> {
    let text = fs::read_to_string(data_dir().join("api.json")).ok()?;
    serde_json::from_str(&text).ok()
}

/// 极简 HTTP 请求（只用于本机的 health / shutdown，不值得为此引入 HTTP 客户端库）。
fn http(method: &str, url: &str, token: Option<&str>, timeout: Duration) -> Option<(u16, String)> {
    let rest = url.strip_prefix("http://")?;
    let (hostport, path) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "/"),
    };
    let addr = hostport.to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&addr, timeout).ok()?;
    stream.set_read_timeout(Some(timeout)).ok()?;
    stream.set_write_timeout(Some(timeout)).ok()?;
    let auth = token.map(|t| format!("Authorization: Bearer {t}\r\n")).unwrap_or_default();
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: {hostport}\r\n{auth}Content-Length: 0\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(req.as_bytes()).ok()?;
    let mut buf = String::new();
    stream.read_to_string(&mut buf).ok()?;
    let status = buf.split_whitespace().nth(1)?.parse().ok()?;
    let body = buf.split_once("\r\n\r\n").map(|(_, b)| b.to_string()).unwrap_or_default();
    Some((status, body))
}

fn healthy(url: &str) -> bool {
    let health = format!("{}/api/health", url.trim_end_matches('/'));
    matches!(http("GET", &health, None, Duration::from_millis(800)), Some((200, body)) if body.contains("\"ok\":true"))
}

fn new_token() -> String {
    let mut bytes = [0u8; 24];
    getrandom::fill(&mut bytes).expect("系统随机数不可用");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

impl EngineState {
    /// 返回可用的连接；必要时拉起引擎（阻塞，最长 START_TIMEOUT）。`resource_dir` 是应用的资源目录（打包版里有引擎）。
    pub fn connect(&self, resource_dir: Option<&Path>) -> Result<Connection, String> {
        let mut guard = self.inner.lock().map_err(|_| "内部状态损坏".to_string())?;

        // 1. 自己拉起的还活着
        if let Some(sp) = guard.as_mut() {
            let alive = matches!(sp.child.try_wait(), Ok(None));
            if alive && healthy(&sp.conn.url) {
                return Ok(sp.conn.clone());
            }
            log::warn!("拉起的引擎已经不在了，重新连接");
            *guard = None;
        }

        // 2. 已有服务（开发时手动 serve，或上次留下的）
        if let Some(info) = read_api_info() {
            if healthy(&info.url) {
                log::info!("连接已在运行的引擎 {}（pid {}）", info.url, info.pid);
                return Ok(Connection { url: info.url, token: info.token, spawned: false, pid: info.pid });
            }
        }

        // 3. 自己拉起
        let sp = spawn(launch_target(resource_dir)?)?;
        let conn = sp.conn.clone();
        *guard = Some(sp);
        Ok(conn)
    }

    /// 应用退出时调用：只关自己拉起的引擎。
    pub fn shutdown(&self) {
        let Ok(mut guard) = self.inner.lock() else { return };
        let Some(mut sp) = guard.take() else { return };
        let url = format!("{}/api/shutdown", sp.conn.url.trim_end_matches('/'));
        let asked = http("POST", &url, sp.conn.token.as_deref(), Duration::from_secs(2)).is_some();
        if asked {
            let end = Instant::now() + SHUTDOWN_TIMEOUT;
            while Instant::now() < end {
                if matches!(sp.child.try_wait(), Ok(Some(_))) {
                    log::info!("引擎已正常退出");
                    return;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
        }
        log::warn!("引擎没有按时退出，强制结束");
        let _ = sp.child.kill();
        // 作业对象随 sp 一起释放，会结束剩下的子进程
    }
}

fn spawn(target: Launch) -> Result<Spawned, String> {
    let token = new_token();
    let logs = data_dir().join("logs");
    fs::create_dir_all(&logs).map_err(|e| format!("创建日志目录失败：{e}"))?;
    let out = File::create(logs.join("engine-stdout.log")).map_err(|e| format!("创建日志文件失败：{e}"))?;
    let err = out.try_clone().map_err(|e| e.to_string())?;

    let (mut cmd, dir) = match target {
        Launch::Bundled(exe) => {
            let dir = exe.parent().map(Path::to_path_buf).unwrap_or_default();
            let mut c = Command::new(&exe);
            c.args(["serve", "--port", "0"]);
            (c, dir)
        }
        Launch::Source(dir) => {
            let dir = dir.canonicalize().map_err(|e| format!("找不到引擎目录 {}：{e}", dir.display()))?;
            let venv_python = dir.join(".venv").join("Scripts").join("python.exe");
            let c = if venv_python.exists() {
                let mut c = Command::new(venv_python);
                c.args(["-m", "e7helper.cli", "serve", "--port", "0"]);
                c
            } else {
                let mut c = Command::new("python");
                c.args(["-m", "uv", "run", "e7helper", "serve", "--port", "0"]);
                c
            };
            (c, dir)
        }
    };
    // 开发调试用：附加参数，例如 E7_ENGINE_ARGS="--no-connect --paused"（不连模拟器、计划暂停）
    if let Ok(extra) = std::env::var("E7_ENGINE_ARGS") {
        cmd.args(extra.split_whitespace());
    }
    cmd.current_dir(&dir)
        .env("E7_API_TOKEN", &token)
        .env("PYTHONIOENCODING", "utf-8") // 冻结版忽略它，spec 里直接开了 UTF-8 模式
        .stdin(Stdio::null())
        .stdout(Stdio::from(out))
        .stderr(Stdio::from(err));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    log::info!("拉起引擎：{:?}（目录 {}）", cmd, dir.display());
    let mut child = cmd.spawn().map_err(|e| format!("启动引擎失败：{e}"))?;
    #[cfg(windows)]
    let job = job::Job::new_kill_on_close().and_then(|j| j.assign(&child).map(|_| j)).map_err(|e| {
        let _ = child.kill();
        format!("创建作业对象失败：{e}")
    })?;

    let pid = child.id();
    let started = Instant::now();
    loop {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "引擎启动后退出了（{status}），详情见 {}",
                logs.join("engine-stdout.log").display()
            ));
        }
        // 开发版 api.json 里写的是真正解释器的 pid（venv 转发器的子进程），所以按 token 认自己的服务
        if let Some(info) = read_api_info() {
            if info.token.as_deref() == Some(token.as_str()) && healthy(&info.url) {
                log::info!("引擎已就绪：{}（{:.1} 秒）", info.url, started.elapsed().as_secs_f32());
                let conn = Connection { url: info.url, token: Some(token), spawned: true, pid };
                return Ok(Spawned {
                    child,
                    conn,
                    #[cfg(windows)]
                    job,
                });
            }
        }
        if started.elapsed() > START_TIMEOUT {
            let _ = child.kill();
            return Err(format!("引擎 {} 秒内没有就绪", START_TIMEOUT.as_secs()));
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// 关闭句柄时结束作业里所有进程。
    pub struct Job(HANDLE);

    // HANDLE 是裸指针；作业对象句柄可以跨线程使用
    unsafe impl Send for Job {}

    impl Job {
        pub fn new_kill_on_close() -> Result<Self, String> {
            unsafe {
                let h = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if h.is_null() {
                    return Err(std::io::Error::last_os_error().to_string());
                }
                let job = Job(h);
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let ok = SetInformationJobObject(
                    h,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if ok == 0 {
                    return Err(std::io::Error::last_os_error().to_string());
                }
                Ok(job)
            }
        }

        pub fn assign(&self, child: &Child) -> Result<(), String> {
            let ok = unsafe { AssignProcessToJobObject(self.0, child.as_raw_handle() as HANDLE) };
            if ok == 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }
            Ok(())
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}
