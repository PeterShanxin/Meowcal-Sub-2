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
            *slot = Some(child);
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
