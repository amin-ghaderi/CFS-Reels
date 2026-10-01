mod credentials;
mod engine;
mod playback;
pub mod launch;
pub mod paths;
pub mod ready;
pub mod redact;
pub mod transport;

use tauri::{LogicalSize, Manager};

/// Preferred size is 1200×720. The minimum in tauri.conf.json is 800×520.
/// On a smaller work area the window is clamped so the status bar stays reachable.
fn fit_initial_window(app: &tauri::App) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let Ok(Some(monitor)) = window.current_monitor() else {
        return;
    };
    let scale = monitor.scale_factor();
    if scale <= 0.0 {
        return;
    }
    let area = monitor.work_area();
    let max_width = (area.size.width as f64 / scale) - 24.0;
    let max_height = (area.size.height as f64 / scale) - 24.0;
    if max_width < 480.0 || max_height < 360.0 {
        return;
    }
    let _ = window.set_size(LogicalSize::new(1200.0_f64.min(max_width), 720.0_f64.min(max_height)));
}

/// Desktop shell. The identifier in tauri.conf.json (`local.amix.desktop.dev`) is provisional.
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(engine::EngineState::new())
        .setup(|app| {
            fit_initial_window(app);
            app.state::<engine::EngineState>()
                .attach_app(app.handle().clone());
            engine::schedule_start(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine::desktop_session_snapshot,
            engine::engine_status,
            engine::engine_retry,
            engine::engine_request,
            engine::join_project_path,
            engine::set_provider_credential,
            engine::credential_configured,
            engine::remove_provider_credential,
            playback::prepare_playback,
            playback::release_playback,
        ])
        .build(tauri::generate_context!())
        .expect("AMIX desktop failed to start")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                app.state::<engine::EngineState>().shutdown();
            }
        });
}
