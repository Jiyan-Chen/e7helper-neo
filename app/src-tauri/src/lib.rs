mod engine;

use engine::{Connection, EngineState};
use tauri::{Manager, RunEvent};

/// 前端启动时调用：拿到引擎的地址和 token（必要时拉起引擎，可能要几秒到几十秒）。
#[tauri::command]
async fn engine_connection(app: tauri::AppHandle) -> Result<Connection, String> {
    tauri::async_runtime::spawn_blocking(move || app.state::<EngineState>().connect())
        .await
        .map_err(|e| e.to_string())?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(if cfg!(debug_assertions) { log::LevelFilter::Info } else { log::LevelFilter::Warn })
                .build(),
        )
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![engine_connection])
        .build(tauri::generate_context!())
        .expect("创建应用失败");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<EngineState>().shutdown();
        }
    });
}
