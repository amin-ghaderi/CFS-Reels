fn main() {
    let target = std::env::var("TARGET").unwrap_or_default();
    if target.contains("windows") {
        // tauri-build embeds the Common Controls 6 manifest only in the application
        // binary. Library and integration test executables then bind comctl32 v5 and
        // Windows refuses to start them (STATUS_ENTRYPOINT_NOT_FOUND). Put the same
        // dependency on the linker so every artifact, including the test harness, gets it.
        tauri_build::try_build(tauri_build::Attributes::new().windows_attributes(
            tauri_build::WindowsAttributes::new_without_app_manifest(),
        ))
        .expect("failed to run tauri-build");
        println!("cargo:rustc-link-arg=/MANIFEST:EMBED");
        println!(
            "cargo:rustc-link-arg=/MANIFESTDEPENDENCY:type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'"
        );
    } else {
        tauri_build::build();
    }
}
