"""Exercise signed Windows installers only on disposable GitHub-hosted runners."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from installer_assets import digest, require, require_hosted_work, verify_assets, verify_installed

HELPER = Path(__file__).with_name("inspect-installer-window.ps1")
PINS = Path(__file__).resolve().parents[1] / "config/installer-acceptance.json"


def wait_for(check, description: str, timeout: int = 60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.5)
    raise RuntimeError(f"Timed out: {description}")


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.root = args.work.resolve()
        self.report = {
            "at": datetime.now(UTC).isoformat(),
            "architecture": args.architecture,
            "passed": False,
            "productionUpdaterExercised": False,
            "scope": "Exact signed installer cancellation, native UI and in-place upgrade; not the production updater endpoint.",
            "phases": [],
        }
        self.tracked = self.root / "tracked.json"
        self.environment = dict(os.environ)
        self.destination = self.root / "installed"
        self.executable = self.destination / "meowcal-sub-2-shell.exe"

    def record(self):
        (self.root / "report.json").write_text(json.dumps(self.report, indent=2) + "\n")

    def native(self, action="Inspect", pid=None):
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            str(HELPER),
            "-WorkRoot",
            str(self.root),
            "-Action",
            action,
            "-Tracked",
            str(self.tracked),
        ]
        if pid is not None:
            command.extend(["-AppPid", str(pid)])
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return json.loads(result.stdout)

    def spawn(self, path, *arguments):
        child = subprocess.Popen(
            [str(path), *arguments],
            env=self.environment,
            cwd=self.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return child

    def track(self):
        rows = self.native("Processes")
        self.tracked.write_text(json.dumps(rows))
        return rows

    def close(self, pid):
        rows = self.track()
        require(any(row["pid"] == pid for row in rows), "App PID no longer belongs to acceptance.")
        self.native("Close", pid)
        wait_for(lambda: not self.native("Remaining"), "graceful app and child-process exit", 40)
        return {"trackedProcessCount": len(rows), "remaining": []}

    def setup_profile(self, phase):
        self.profile = self.root / phase
        for name in ("home", "local", "temp", "meowcal-sub-2"):
            (self.profile / name).mkdir(parents=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.config = self.profile / "meowcal-sub-2/config.toml"
        self.config.write_text(
            f'[languages]\nsource="en"\ntarget="en"\n[overlay]\nport={self.port}\nfont_size=37\n[sync]\nbias_ms=500\n'
        )
        self.marker = self.profile / "home/.cache/meowcal-sub-2/acceptance.srt"
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text("1\n00:00:01,000 --> 00:00:02,000\nSynthetic retained subtitle\n")
        self.environment.update(
            APPDATA=str(self.profile),
            LOCALAPPDATA=str(self.profile / "local"),
            USERPROFILE=str(self.profile / "home"),
            TEMP=str(self.profile / "temp"),
            TMP=str(self.profile / "temp"),
            WEBVIEW2_USER_DATA_FOLDER=str(self.profile / "webview"),
            WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--force-renderer-accessibility",
            MEOWCAL_CORE_EXE=str(self.destination / "core/meowcal-core.exe"),
        )

    def registry_version(self, version):
        rows = self.native("Installations")
        return (
            len(rows) == 1
            and rows[0]["DisplayVersion"] == version
            and Path(rows[0]["InstallLocation"]).resolve() == self.destination
        )

    def install(self, installer, version, upgrade=False):
        arguments = ["/S", "/NS"]
        if upgrade:
            arguments += ["/UPDATE", "/R"]
        arguments += ["/D=" + str(self.destination)]
        process = self.spawn(installer, *arguments)
        require(process.wait(timeout=150) == 0, "Installer failed.")
        wait_for(
            lambda: self.registry_version(version) and self.executable.is_file(),
            "installed registry and executable",
        )
        return {"exitCode": 0, "version": version, "arguments": arguments}

    def api(self, value=None):
        runtime = json.loads((self.profile / "meowcal-sub-2/runtime.json").read_text())
        require(runtime["port"] == self.port, "Runtime port differs from isolated profile.")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/config",
            data=json.dumps(value).encode() if value is not None else None,
            headers={"X-Meowcal-Token": runtime["token"], "Content-Type": "application/json"},
            method="PUT" if value is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def studio(self, pid):
        last = []

        def ready():
            nonlocal last
            try:
                last = self.native(pid=pid)
            except subprocess.CalledProcessError:
                return False
            names = [row["name"] for row in last if not row["offscreen"]]
            return (
                any(
                    row["type"] == "ControlType.Document"
                    and not row["offscreen"]
                    and row["name"] == "Meowcal Sub 2"
                    for row in last
                )
                and "Settings" in names
                and (
                    "SETUP REQUIRED" in names
                    or any(row["type"] == "ControlType.Edit" for row in last)
                )
            )

        try:
            wait_for(ready, "native Studio accessibility", 90)
            self.native("Settings", pid)
            wait_for(
                lambda: any(
                    row["type"] == "ControlType.Edit" and not row["offscreen"]
                    for row in self.native(pid=pid)
                ),
                "native Settings editable controls",
            )
        except Exception:
            self.report["lastNativeControls"] = last
            raise
        settings = self.api()
        require(settings["overlay"]["port"] == self.port, "Native app used the wrong profile.")
        return {"pid": pid, "studioRendered": True, "settingsOpened": True}

    def uninstall(self):
        config_hash, marker_hash = digest(self.config), digest(self.marker)
        child = self.spawn(self.destination / "uninstall.exe", "/S")
        require(child.wait(timeout=90) == 0, "Uninstaller failed.")
        wait_for(
            lambda: not self.executable.exists() and not self.native("Installations"),
            "uninstall removal",
        )
        require(
            digest(self.config) == config_hash and digest(self.marker) == marker_hash,
            "Default uninstall removed retained settings or subtitles.",
        )
        return {
            "exitCode": 0,
            "applicationRemoved": True,
            "registryRemoved": True,
            "configAndSubtitleCacheRetained": True,
        }

    def cancel(self, installer):
        child = self.spawn(installer, "/NS", "/D=" + str(self.destination))

        def cancel_visible():
            return any(
                row["name"].replace("&", "") == "Cancel" and not row["offscreen"]
                for row in self.native(pid=child.pid)
            )

        wait_for(cancel_visible, "installer Cancel button")
        self.native("Cancel", child.pid)
        if child.poll() is None:
            # NSIS may ask for confirmation on a separate dialog owned by the same PID.
            def cancelled():
                if child.poll() is not None:
                    return True
                controls = self.native(pid=child.pid)
                if any(row["name"].replace("&", "") == "Yes" for row in controls):
                    self.native("Yes", child.pid)
                return False

            wait_for(cancelled, "installer cancellation")
        require(
            not self.native("Installations") and not self.executable.exists(),
            "Cancelled installer changed installation.",
        )
        return {
            "phase": "installer-cancel-before-install",
            "exitCode": child.returncode,
            "noInstallationCreated": True,
            "appUpdaterLaterNotExercised": True,
        }

    def run(self):
        require_hosted_work(self.root, dict(os.environ))
        require(
            not self.native("Installations"), "Runner already contains Sub 2; refusing to alter it."
        )
        self.root.mkdir()
        self.tracked.write_text("[]")
        self.record()
        try:
            pins = json.loads(PINS.read_text())
            packages = {}
            for role in ("receiver", "target"):
                installer, portable = verify_assets(
                    self.args.assets, pins[role], self.args.architecture, self.args.verifier
                )
                owned = self.root / installer.name
                shutil.copyfile(installer, owned)
                packages[role] = (owned, portable)
            self.report["verifiedBuilds"] = pins
            self.setup_profile("formal")
            self.report["phases"].append(self.cancel(packages["target"][0]))
            self.record()
            formal = {
                "phase": "fresh-formal-install",
                "installer": self.install(packages["target"][0], "0.2.1"),
            }
            self.report["phases"].append(formal)
            formal["payload"] = verify_installed(
                self.destination, packages["target"][1], self.args.architecture
            )
            app = self.spawn(self.executable)
            formal["native"] = self.studio(app.pid)
            formal["close"] = self.close(app.pid)
            formal["uninstall"] = self.uninstall()
            self.record()
            self.setup_profile("upgrade")
            upgrade = {
                "phase": "in-place-signed-receiver-upgrade",
                "receiver": self.install(packages["receiver"][0], "0.2.0"),
            }
            self.report["phases"].append(upgrade)
            upgrade["receiverPayload"] = verify_installed(
                self.destination, packages["receiver"][1], self.args.architecture
            )
            old = self.spawn(self.executable)
            upgrade["oldNative"] = self.studio(old.pid)
            settings = self.api()
            settings["overlay"]["fontSize"], settings["sync"]["biasMs"] = 41, 750
            self.api(settings)
            config_hash, marker_hash = digest(self.config), digest(self.marker)
            upgrade["oldClose"] = self.close(old.pid)
            upgrade["installer"] = self.install(packages["target"][0], "0.2.1", upgrade=True)

            def restarted():
                return [
                    row
                    for row in self.native("Processes")
                    if Path(row["path"]).resolve() == self.executable and row["pid"] != old.pid
                ]

            rows = wait_for(restarted, "automatic installer restart", 100)
            require(len(rows) == 1, "Expected one automatically restarted shell.")
            pid = rows[0]["pid"]
            upgrade["newNative"] = self.studio(pid)
            upgrade["automaticRestart"] = {"oldPid": old.pid, "newPid": pid, "manualLaunch": False}
            settings = self.api()
            require(
                settings["overlay"]["fontSize"] == 41
                and settings["sync"]["biasMs"] == 750
                and digest(self.config) == config_hash
                and digest(self.marker) == marker_hash,
                "Settings or subtitle cache changed during upgrade.",
            )
            upgrade["settingsAndCacheRetained"] = True
            upgrade["targetPayload"] = verify_installed(
                self.destination, packages["target"][1], self.args.architecture
            )
            upgrade["newClose"] = self.close(pid)
            upgrade["uninstall"] = self.uninstall()
            self.report["passed"] = True
        except Exception as error:
            self.report["error"] = f"{type(error).__name__}: {error}"
        finally:
            self.cleanup()
            self.record()
        require(self.report["passed"], "Acceptance failed; see sanitized report.json.")

    def cleanup(self):
        try:
            # Retain pre-close descendants even if their parent has already exited.
            previous = json.loads(self.tracked.read_text())
            current = self.native("Processes")
            self.tracked.write_text(
                json.dumps(previous + [row for row in current if row not in previous])
            )
            remaining = self.native("Remaining")
            if remaining:
                self.report["passed"] = False
                self.report["forcedCleanup"] = True
                self.native("Cleanup")
                wait_for(lambda: not self.native("Remaining"), "forced owned-process cleanup", 30)
            if (self.destination / "uninstall.exe").exists():
                self.report["cleanupUninstall"] = self.uninstall()
            self.report["cleanup"] = {
                "remainingProcesses": self.native("Remaining") + self.native("Processes"),
                "remainingInstallations": self.native("Installations"),
            }
            require(not self.report["cleanup"]["remainingProcesses"], "Owned processes remain.")
            require(not self.report["cleanup"]["remainingInstallations"], "Installation remains.")
            for name in ("formal", "upgrade", "installed"):
                folder = self.root / name
                if folder.exists():
                    require(
                        folder.resolve().is_relative_to(self.root), "Cleanup escaped work root."
                    )
                    for attempt in range(5):
                        try:
                            shutil.rmtree(folder)
                            break
                        except PermissionError:
                            if attempt == 4:
                                raise
                            time.sleep(1)
            self.report["cleanup"]["profilesRemoved"] = True
        except Exception as error:
            self.report["passed"] = False
            self.report["cleanupError"] = f"{type(error).__name__}: {error}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=("arm64", "x64"), required=True)
    for name in ("assets", "verifier", "work"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    Acceptance(parser.parse_args()).run()
