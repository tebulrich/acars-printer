fn main() {
    // Release builds stage the frozen Python bridge here; the shell embeds it
    // and extracts under LocalAppData so users only run one EXE.
    println!("cargo:rerun-if-changed=embedded/acars-bridge.exe");
    println!("cargo:rustc-check-cfg=cfg(has_embedded_sidecar)");
    if std::path::Path::new("embedded/acars-bridge.exe").is_file() {
        println!("cargo:rustc-cfg=has_embedded_sidecar");
    }

    #[cfg(windows)]
    {
        // UAC on every launch — WinDivert / Connect needs Administrator.
        // Keep Common Controls v6 so Tauri dialogs render correctly.
        let windows = tauri_build::WindowsAttributes::new().app_manifest(
            r#"
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <dependency>
    <dependentAssembly>
      <assemblyIdentity
        type="win32"
        name="Microsoft.Windows.Common-Controls"
        version="6.0.0.0"
        processorArchitecture="*"
        publicKeyToken="6595b64144ccf1df"
        language="*"
      />
    </dependentAssembly>
  </dependency>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false" />
      </requestedPrivileges>
    </security>
  </trustInfo>
</assembly>
"#,
        );
        tauri_build::try_build(tauri_build::Attributes::new().windows_attributes(windows))
            .expect("failed to run build script");
        return;
    }

    #[cfg(not(windows))]
    tauri_build::build();
}
