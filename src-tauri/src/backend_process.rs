use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Clone)]
pub(crate) struct BackendProcess(Arc<Mutex<Option<Child>>>);

impl BackendProcess {
    pub(crate) fn new() -> Self {
        Self(Arc::new(Mutex::new(None)))
    }
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repo root")
        .to_path_buf()
}

fn python_executable() -> PathBuf {
    if let Ok(path) = std::env::var("MEOWCAL_PYTHON") {
        let candidate = PathBuf::from(path);
        if candidate.exists() {
            return candidate;
        }
    }
    repo_root().join(".venv").join("Scripts").join("python.exe")
}

fn bundled_core_executable(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resource_dir()
        .map(|directory| directory.join("core").join("meowcal-core.exe"))
        .map_err(|error| format!("Core resource directory is unavailable: {error}"))
}

pub(crate) fn spawn_backend(app: &AppHandle, process: &BackendProcess) {
    let python = python_executable();
    let core_executable = match bundled_core_executable(app) {
        Ok(path) => path,
        Err(error) => {
            crate::log_shell_event(
                "backend.spawn.failed",
                serde_json::json!({ "error": error }),
            );
            return;
        }
    };
    crate::log_shell_event(
        "backend.spawn.requested",
        serde_json::json!({
            "python": python.display().to_string(),
            "using_repo_venv": python.exists(),
            "core_executable": core_executable.display().to_string(),
        }),
    );
    let mut command = if python.exists() {
        let mut command = Command::new(python);
        command.current_dir(repo_root());
        command.args(["-m", "meocosub2.cli", "serve"]);
        command
    } else {
        let mut command = Command::new("python");
        command.current_dir(repo_root());
        command.args(["-m", "meocosub2.cli", "serve"]);
        command
    };
    command.env("MEOWCAL_CORE_EXE", core_executable);

    #[cfg(target_os = "windows")]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.spawn() {
        Ok(child) => {
            let pid = child.id();
            // Job membership is inherited, so enrolling the backend before it
            // starts Core keeps both processes bound to the shell lifetime.
            crate::process_lifetime::attach_to_app_lifetime(&child);
            crate::log_shell_event("backend.spawn.started", serde_json::json!({ "pid": pid }));
            *process.0.lock().expect("backend process lock") = Some(child);
        }
        Err(error) => {
            crate::log_shell_event(
                "backend.spawn.failed",
                serde_json::json!({ "error": error.to_string() }),
            );
        }
    }
}
