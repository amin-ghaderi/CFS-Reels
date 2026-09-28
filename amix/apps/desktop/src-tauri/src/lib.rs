mod engine;
pub mod launch;
pub mod paths;
pub mod ready;
pub mod transport;

use tauri::Manager;

/// Desktop shell. The identifier in tauri.conf.json (`local.amix.desktop.dev`) is provisional.
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(engine::EngineState::new())
        .setup(|app| {
            engine::schedule_start(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine::engine_status,
            engine::engine_retry,
            engine::engine_request,
            engine::join_project_path,
        ])
        .build(tauri::generate_context!())
        .expect("AMIX desktop failed to start")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                app.state::<engine::EngineState>().shutdown();
            }
        });
}
