use std::path::Path;
#[cfg(debug_assertions)]
use std::path::PathBuf;
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

#[cfg(debug_assertions)]
fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repo root")
        .to_path_buf()
}

#[cfg(debug_assertions)]
fn python_executable() -> PathBuf {
    if let Ok(path) = std::env::var("MEOWCAL_PYTHON") {
        let candidate = PathBuf::from(path);
        if candidate.exists() {
            return candidate;
        }
    }
    repo_root().join(".venv").join("Scripts").join("python.exe")
}

#[cfg(any(not(debug_assertions), test))]
fn packaged_backend_command(resources: &Path) -> Result<Command, String> {
    let directory = resources.join("backend");
    let python = directory.join("python.exe");
    if !python.is_file() {
        return Err(format!("Bundled Python is missing: {}", python.display()));
    }
    let mut command = Command::new(python);
    command.current_dir(directory);
    command.args(["-I", "-B", "-m", "meocosub2.cli", "serve"]);
    command.env(
        "MEOWCAL_CORE_EXE",
        resources.join("core").join("meowcal-core.exe"),
    );
    Ok(command)
}

#[cfg(not(debug_assertions))]
fn backend_command(resources: &Path) -> Result<Command, String> {
    // A release must never run code from PATH, an editable checkout, or PYTHONPATH.
    packaged_backend_command(resources)
}

#[cfg(debug_assertions)]
fn backend_command(resources: &Path) -> Result<Command, String> {
    let python = python_executable();
    let mut command = Command::new(if python.exists() {
        python
    } else {
        "python".into()
    });
    command.current_dir(repo_root());
    command.args(["-m", "meocosub2.cli", "serve"]);
    command.env(
        "MEOWCAL_CORE_EXE",
        resources.join("core").join("meowcal-core.exe"),
    );
    Ok(command)
}

fn contain_backend(
    mut child: Child,
    attach: impl FnOnce(&Child) -> Result<(), String>,
) -> Result<Child, String> {
    if let Err(error) = attach(&child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    Ok(child)
}

/// Retry can call `spawn_backend` while a prior child is still alive but
/// unresponsive; without this, the old process would only be reaped when the
/// whole app exits, leaking a resident `llama-server` per retry.
fn kill_previous_backend(slot: &mut Option<Child>) {
    if let Some(mut child) = slot.take() {
        if let Ok(None) = child.try_wait() {
            let _ = child.kill();
        }
        let _ = child.wait();
    }
}

pub(crate) fn spawn_backend(app: &AppHandle, process: &BackendProcess) {
    // Held for the whole kill/spawn/store sequence: two retry threads racing
    // on a partial lock could both see an empty slot, both spawn, and the
    // later store would silently orphan the earlier child.
    let mut slot = process.0.lock().expect("backend process lock");
    kill_previous_backend(&mut slot);
    let resources = match app.path().resource_dir() {
        Ok(path) => path,
        Err(error) => {
            crate::log_shell_event(
                "backend.spawn.failed",
                serde_json::json!({ "error": error.to_string() }),
            );
            return;
        }
    };
    let core_executable = resources.join("core").join("meowcal-core.exe");
    let mut command = match backend_command(&resources) {
        Ok(command) => command,
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
            "python": command.get_program().to_string_lossy(),
            "packaged": !cfg!(debug_assertions),
            "core_executable": core_executable.display().to_string(),
        }),
    );

    #[cfg(target_os = "windows")]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.spawn() {
        Ok(child) => {
            let pid = child.id();
            // Job membership is inherited, so enrolling the backend before it
            // starts Core keeps both processes bound to the shell lifetime.
            match contain_backend(child, crate::process_lifetime::attach_to_app_lifetime) {
                Ok(child) => {
                    crate::log_shell_event(
                        "backend.spawn.started",
                        serde_json::json!({ "pid": pid }),
                    );
                    *slot = Some(child);
                }
                Err(error) => crate::log_shell_event(
                    "backend.spawn.failed",
                    serde_json::json!({ "error": error }),
                ),
            }
        }
        Err(error) => {
            crate::log_shell_event(
                "backend.spawn.failed",
                serde_json::json!({ "error": error.to_string() }),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Barrier;

    #[test]
    fn failed_lifetime_attachment_terminates_and_reaps_the_backend() {
        let child = Command::new("ping")
            .args(["-n", "10", "127.0.0.1"])
            .stdout(std::process::Stdio::null())
            .spawn()
            .expect("fixture process");
        let pid = child.id();
        let result = contain_backend(child, |_| Err("fixture attachment failure".into()));
        assert!(result.is_err());
        assert!(!is_pid_running(pid));
    }

    #[test]
    fn missing_packaged_python_does_not_fall_back_to_a_developer_install() {
        let missing = std::env::temp_dir().join("meowcal-no-packaged-runtime");
        assert!(packaged_backend_command(&missing).is_err());
    }

    #[test]
    fn packaged_python_uses_only_its_own_runtime_directory() {
        let resources =
            std::env::temp_dir().join(format!("meowcal-package-test-{}", std::process::id()));
        let backend = resources.join("backend");
        std::fs::create_dir_all(&backend).expect("fixture directory");
        std::fs::write(backend.join("python.exe"), []).expect("fixture executable");
        let command = packaged_backend_command(&resources).expect("packaged command");
        assert_eq!(command.get_program(), backend.join("python.exe"));
        assert_eq!(command.get_current_dir(), Some(backend.as_path()));
        let core = resources.join("core").join("meowcal-core.exe");
        assert!(command
            .get_envs()
            .any(|(key, value)| key == "MEOWCAL_CORE_EXE" && value == Some(core.as_os_str())));
        assert_eq!(
            command.get_args().collect::<Vec<_>>(),
            ["-I", "-B", "-m", "meocosub2.cli", "serve"]
        );
        std::fs::remove_dir_all(resources).expect("remove fixture");
    }

    fn is_pid_running(pid: u32) -> bool {
        std::process::Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}")])
            .output()
            .map(|output| String::from_utf8_lossy(&output.stdout).contains(&pid.to_string()))
            .unwrap_or(false)
    }

    /// Reproduces a double-clicked Retry: two threads racing to replace the
    /// same backend slot. Before the fix, a lock held only for the kill step
    /// let both threads spawn and the later store silently orphan the
    /// earlier child; this asserts the loser is actually dead, not just
    /// evicted from the slot.
    #[test]
    fn concurrent_retries_serialize_and_never_orphan_a_child() {
        let process = BackendProcess::new();
        let barrier = Arc::new(Barrier::new(2));
        let pids = Arc::new(Mutex::new(Vec::new()));

        let race_retry =
            |process: BackendProcess, barrier: Arc<Barrier>, pids: Arc<Mutex<Vec<u32>>>| {
                barrier.wait();
                let mut slot = process.0.lock().expect("backend process lock");
                kill_previous_backend(&mut slot);
                let child = Command::new("ping")
                    .args(["-n", "5", "127.0.0.1"])
                    .stdout(std::process::Stdio::null())
                    .spawn()
                    .expect("the fixture process should start");
                pids.lock().expect("pid log lock").push(child.id());
                *slot = Some(child);
            };

        let t1 = {
            let (process, barrier, pids) =
                (process.clone(), Arc::clone(&barrier), Arc::clone(&pids));
            std::thread::spawn(move || race_retry(process, barrier, pids))
        };
        let t2 = {
            let (process, barrier, pids) =
                (process.clone(), Arc::clone(&barrier), Arc::clone(&pids));
            std::thread::spawn(move || race_retry(process, barrier, pids))
        };
        t1.join().expect("retry thread 1 should not panic");
        t2.join().expect("retry thread 2 should not panic");

        let spawned_pids = pids.lock().expect("pid log lock").clone();
        assert_eq!(spawned_pids.len(), 2, "both retries should have spawned");

        let winner = process
            .0
            .lock()
            .expect("backend process lock")
            .take()
            .expect("the last retry to run should leave a live child in the slot");
        let winner_pid = winner.id();
        let loser_pid = spawned_pids
            .into_iter()
            .find(|pid| *pid != winner_pid)
            .expect("the two spawned pids must differ");

        assert!(
            !is_pid_running(loser_pid),
            "the losing retry's child must be killed, not left running untracked"
        );

        let mut winner = winner;
        let _ = winner.kill();
        let _ = winner.wait();
    }

    #[test]
    fn kill_previous_backend_reaps_a_still_running_child() {
        let mut child = Command::new("ping")
            .args(["-n", "10", "127.0.0.1"])
            .stdout(std::process::Stdio::null())
            .spawn()
            .expect("the fixture process should start");
        let pid = child.id();
        assert!(
            matches!(child.try_wait(), Ok(None)),
            "fixture process should still be running before the test"
        );

        let process = BackendProcess::new();
        let mut slot = process.0.lock().expect("backend process lock");
        *slot = Some(child);

        kill_previous_backend(&mut slot);

        assert!(slot.is_none(), "the slot should be cleared after reaping");
        assert!(
            !is_pid_running(pid),
            "the previous child must be killed, not orphaned"
        );
    }
}
