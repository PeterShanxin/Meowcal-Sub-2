// =============================================================================
// PROCESS LIFETIME - children die when this process dies
// =============================================================================
// The shell starts the Python backend, and the backend starts `llama-server.exe`
// with a multi-gigabyte model resident. Both are stopped on the graceful path,
// but Windows does not tie a child's lifetime to its parent's, so every other
// way the shell can end leaves the backend running and the engine with it:
//
//   - the installer closing the running app to replace its files,
//   - Task Manager, `Stop-Process`, or any other TerminateProcess,
//   - a panic that aborts, or the WebView taking the process down with it,
//   - session logoff and shutdown, where the exit event is not delivered.
//
// Each of those leaks an engine, and they accumulate one per crash until the
// machine is out of memory.
//
// The fix is a job object created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The
// backend is assigned to it and the only handle to it is held by this process.
// However this process ends, Windows closes that handle, and closing the last
// handle to a job terminates everything inside it. No cleanup code has to run,
// which is the point: the paths that leak are exactly the paths where our code
// does not get to run. Job membership is inherited, so the engine the backend
// spawns joins the same job without the shell knowing the engine exists.
//
// Sweeping engines stranded by *earlier* runs is the other half, and lives in
// `meocosub2.engine.orphans` - the backend already resolves the engine's path,
// and the shell would have to duplicate that to do the same job.
// =============================================================================

#[cfg(target_os = "windows")]
mod windows_impl {
    use crate::log_shell_event;
    use std::process::Child;
    use std::sync::OnceLock;
    use windows::Win32::Foundation::{CloseHandle, HANDLE};
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// The job every child joins. Stored as an integer because a raw `HANDLE`
    /// is not `Send`; the value is only ever handed back to Win32.
    ///
    /// Never closed on purpose. The handle has to outlive every child, and this
    /// process dying is what closes it - that is the mechanism, not a leak.
    static JOB: OnceLock<Option<isize>> = OnceLock::new();

    fn job_handle() -> Option<HANDLE> {
        JOB.get_or_init(|| unsafe { create_job() })
            .map(|raw| HANDLE(raw as *mut std::ffi::c_void))
    }

    unsafe fn create_job() -> Option<isize> {
        let job = match CreateJobObjectW(None, windows::core::PCWSTR::null()) {
            Ok(job) => job,
            Err(error) => {
                log_shell_event(
                    "process_lifetime.job.create_failed",
                    serde_json::json!({ "error": error.to_string() }),
                );
                return None;
            }
        };

        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let armed = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const std::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );

        if let Err(error) = armed {
            // A job that does not kill on close is worse than none: children
            // would join it and still outlive us, and we would have logged
            // success.
            log_shell_event(
                "process_lifetime.job.arm_failed",
                serde_json::json!({ "error": error.to_string() }),
            );
            let _ = CloseHandle(job);
            return None;
        }

        log_shell_event("process_lifetime.job.armed", serde_json::json!({}));
        Some(job.0 as isize)
    }

    /// Tie `child` to this process, so it cannot outlive us.
    ///
    /// Best effort by design. Failure leaves the child running exactly as it did
    /// before this module existed, and the explicit shutdown path still covers a
    /// clean exit, so it must never stop the app from starting.
    pub fn attach_to_app_lifetime(child: &Child) {
        use std::os::windows::io::AsRawHandle;

        let Some(job) = job_handle() else {
            return;
        };

        // The handle `Child` already owns, rather than reopening by PID: the PID
        // could have been recycled between the spawn and this call, and
        // assigning a stranger's process to our kill-on-close job would end it.
        let process = HANDLE(child.as_raw_handle());
        if let Err(error) = unsafe { AssignProcessToJobObject(job, process) } {
            log_shell_event(
                "process_lifetime.attach_failed",
                serde_json::json!({ "pid": child.id(), "error": error.to_string() }),
            );
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use std::os::windows::io::AsRawHandle;
        use windows::core::BOOL;
        use windows::Win32::System::JobObjects::IsProcessInJob;

        /// The mechanism itself, against a real child.
        ///
        /// Nothing in this module reports whether enrolment worked - by design,
        /// since a failure must not stop the app - so asking Windows is the only
        /// way to know the engine will actually be taken down with the shell.
        #[test]
        fn a_child_joins_the_job_that_kills_on_close() {
            let mut child = std::process::Command::new("ping")
                .args(["-n", "10", "127.0.0.1"])
                .stdout(std::process::Stdio::null())
                .spawn()
                .expect("the fixture process should start");

            attach_to_app_lifetime(&child);

            let enrolled = job_handle().is_some_and(|job| {
                let mut inside = BOOL(0);
                unsafe {
                    IsProcessInJob(HANDLE(child.as_raw_handle()), Some(job), &mut inside).is_ok()
                }
                .then(|| inside.as_bool())
                .unwrap_or(false)
            });

            let _ = child.kill();
            let _ = child.wait();

            assert!(enrolled, "the child must join the job that kills on close");
        }
    }
}

#[cfg(target_os = "windows")]
pub use windows_impl::attach_to_app_lifetime;

#[cfg(not(target_os = "windows"))]
pub fn attach_to_app_lifetime(_child: &std::process::Child) {}
