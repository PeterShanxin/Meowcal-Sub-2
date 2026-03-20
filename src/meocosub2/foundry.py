"""Foundry Local CLI detection and lightweight status helpers."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

import httpx

from meocosub2.config import AppConfig
from meocosub2.errors import TranslationError

logger = logging.getLogger(__name__)

CLI_CACHE_TTL_S = 5.0
START_ATTEMPT_COOLDOWN_S = 6.0
SERVICE_STABILIZATION_S = 8.0
FAST_PROBE_TIMEOUT_S = 2.0
SLOW_PROBE_TIMEOUT_S = 25.0
TOTAL_WARMUP_TIMEOUT_S = 90.0

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_last_start_attempt = 0.0
_last_service_start = 0.0
_service_url_cache: tuple[float, str | None] = (0.0, None)
_model_cache: tuple[float, list[str]] = (0.0, [])
_package_executable_cache: tuple[float, str | None] = (0.0, None)
_loaded_model_cache: tuple[float, list[str]] = (0.0, [])
_successful_model_cache: tuple[float, str | None] = (0.0, None)


@dataclass
class FoundryStatus:
    cli_available: bool
    service_running: bool
    service_url: str | None
    models: list[str]
    configured_model: str | None
    selected_model: str | None
    phase: str
    notes: str
    probe: dict[str, object] | None = None


def _candidate_commands(args: list[str]) -> list[list[str]]:
    candidates: list[list[str]] = []
    foundry_path = shutil.which("foundry")
    if foundry_path and "WindowsApps" not in foundry_path:
        candidates.append([foundry_path, *args])
    packaged_executable = get_packaged_foundry_executable()
    if packaged_executable:
        candidates.append([packaged_executable, *args])
    if os.name == "nt":
        candidates.append(["cmd", "/c", "foundry", *args])
    else:
        candidates.append(["foundry", *args])
    return candidates


def get_packaged_foundry_executable(force_refresh: bool = False) -> str | None:
    global _package_executable_cache
    cached_at, cached_value = _package_executable_cache
    now = time.time()
    if not force_refresh and now - cached_at < CLI_CACHE_TTL_S:
        return cached_value

    if os.name != "nt":
        _package_executable_cache = (now, None)
        return None

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-AppxPackage Microsoft.FoundryLocal).InstallLocation",
            ],
            capture_output=True,
            text=True,
            timeout=5.0,
            creationflags=_CREATE_NO_WINDOW,
        )
        install_location = (result.stdout or "").strip().splitlines()
        if install_location:
            candidate = os.path.join(install_location[0].strip(), "foundry.exe")
            if os.path.exists(candidate):
                _package_executable_cache = (now, candidate)
                return candidate
    except (OSError, subprocess.SubprocessError):
        pass

    _package_executable_cache = (now, None)
    return None


def _run_foundry(args: list[str], timeout_s: float = 5.0, check: bool = False) -> subprocess.CompletedProcess[str] | None:
    last_error: Exception | None = None
    for command in _candidate_commands(args):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=check,
                creationflags=_CREATE_NO_WINDOW,
            )
            return completed
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = exc
    if check and last_error is not None:
        raise last_error
    return None


def is_cli_available() -> bool:
    result = _run_foundry(["--version"], timeout_s=3.0)
    available = bool(result and result.returncode == 0)
    logger.debug("Foundry CLI available: %s", available)
    return available


def get_service_url(force_refresh: bool = False) -> str | None:
    global _service_url_cache
    cached_at, cached_value = _service_url_cache
    now = time.time()
    if not force_refresh and now - cached_at < CLI_CACHE_TTL_S:
        return cached_value

    result = _run_foundry(["service", "status"], timeout_s=4.0)
    parsed: str | None = None
    if result and result.stdout:
        for line in result.stdout.splitlines():
            parsed = _extract_base_url_from_line(line)
            if parsed:
                break
    _service_url_cache = (now, parsed)
    logger.debug("Foundry service URL: %s", parsed)
    return parsed


def _extract_base_url_from_line(line: str) -> str | None:
    start = line.find("http://")
    if start < 0:
        start = line.find("https://")
    if start < 0:
        return None
    after = line[start:]
    end = len(after)
    for idx, ch in enumerate(after):
        if ch.isspace() or ch in ",)!":
            end = idx
            break
    raw = after[:end].rstrip("/").rstrip(".,;!")
    for suffix in ("/openai/status", "/openai/v1", "/v1"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return raw.rstrip("/")


def get_cached_models(force_refresh: bool = False) -> list[str]:
    global _model_cache
    cached_at, cached_value = _model_cache
    now = time.time()
    if not force_refresh and now - cached_at < CLI_CACHE_TTL_S:
        return list(cached_value)

    result = _run_foundry(["cache", "list"], timeout_s=5.0)
    models: list[str] = []
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            candidate = _extract_model_id(line)
            if candidate and candidate not in models:
                models.append(candidate)
    _model_cache = (now, models)
    logger.debug("Foundry cached models: %s", models)
    return list(models)


def get_loaded_models(force_refresh: bool = False) -> list[str]:
    global _loaded_model_cache
    cached_at, cached_value = _loaded_model_cache
    now = time.time()
    if not force_refresh and now - cached_at < CLI_CACHE_TTL_S:
        return list(cached_value)

    result = _run_foundry(["service", "list"], timeout_s=5.0)
    models: list[str] = []
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            candidate = _extract_model_id(line)
            if candidate and candidate not in models:
                models.append(candidate)
    _loaded_model_cache = (now, models)
    return list(models)


def _extract_model_id(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if lowered.startswith(("cache", "total", "models", "alias")) or "cached on device" in lowered or stripped.startswith("-"):
        return None
    tokens = stripped.split()
    if not tokens:
        return None
    candidate = tokens[-1]
    if ":" not in candidate:
        with_colon = next((token for token in reversed(tokens) if ":" in token), "")
        candidate = with_colon or candidate
    candidate = candidate.strip(",;|[]")
    if ":" not in candidate or len(candidate) < 6:
        return None
    return candidate


def _preferred_model_score(model_id: str) -> int:
    lowered = model_id.lower()
    score = 0
    if any(token in lowered for token in ("chat", "instruct", "mini", "small", "phi-4", "phi-3")):
        score += 500
    if "qwen" in lowered:
        score += 250
    if "generic-cpu" in lowered or lowered.endswith("cpu:2") or lowered.endswith("cpu:4") or lowered.endswith("cpu:5"):
        score += 350
    if any(token in lowered for token in ("qnn", "npu")):
        score -= 100
    if any(token in lowered for token in ("0.5b", "1.5b")):
        score += 450
    elif any(token in lowered for token in ("3b", "4b")):
        score += 250
    elif any(token in lowered for token in ("7b", "8b")):
        score += 120
    if any(token in lowered for token in ("coder", "deepseek", "r1", "distill")):
        score -= 1000
    if any(token in lowered for token in ("14b", "32b", "70b")):
        score -= 250
    return score


def select_model(configured_model: str | None, available_models: list[str]) -> str | None:
    global _successful_model_cache
    _, successful_model = _successful_model_cache
    if configured_model:
        if configured_model in available_models:
            return configured_model
        prefix = f"{configured_model}-"
        prefixed = next((model for model in available_models if model.startswith(prefix)), None)
        if prefixed:
            return prefixed
    if successful_model and successful_model in available_models:
        return successful_model
    loaded_models = get_loaded_models()
    loaded_candidates = [model for model in loaded_models if model in available_models]
    if loaded_candidates:
        return max(loaded_candidates, key=_preferred_model_score)
    if not available_models:
        return None
    return max(available_models, key=_preferred_model_score)


def ensure_service_running() -> bool:
    global _last_start_attempt, _last_service_start
    now = time.time()
    if now - _last_start_attempt < START_ATTEMPT_COOLDOWN_S:
        return False
    _last_start_attempt = now
    result = _run_foundry(["service", "start"], timeout_s=5.0)
    if result is None:
        return False
    _last_service_start = time.time()
    return True


def probe_service(base_url: str, timeout_s: float = FAST_PROBE_TIMEOUT_S) -> tuple[str, str | None]:
    global _last_service_start
    if _last_service_start:
        remaining = SERVICE_STABILIZATION_S - (time.time() - _last_service_start)
        if remaining > 0:
            time.sleep(min(remaining, 1.0))

    candidates = []
    if base_url:
        candidates.extend([f"{base_url}/openai/v1", f"{base_url}/v1"])

    last_error: str | None = None
    for candidate in candidates:
        try:
            logger.debug("Probing Foundry at %s/models", candidate)
            response = httpx.get(f"{candidate}/models", timeout=timeout_s)
            if response.status_code == 200:
                logger.debug("Foundry probe OK at %s", candidate)
                return candidate, None
            last_error = f"HTTP {response.status_code}"
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.HTTPError as exc:
            last_error = str(exc)
    logger.debug("Foundry probe failed: %s", last_error)
    return "", last_error


def probe_chat_completion(api_base: str, model: str, timeout_s: float) -> tuple[bool, str | None]:
    global _successful_model_cache
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "max_tokens": 8,
    }
    try:
        response = httpx.post(f"{api_base}/chat/completions", json=payload, timeout=timeout_s)
        if response.status_code == 200:
            _successful_model_cache = (time.time(), model)
            return True, None
        return False, f"HTTP {response.status_code}"
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.HTTPError as exc:
        return False, str(exc)


def foundry_status(config: AppConfig, probe: bool = False, auto_start: bool = False) -> FoundryStatus:
    logger.debug("foundry_status(probe=%s, auto_start=%s)", probe, auto_start)
    cli_available = is_cli_available()
    service_url = get_service_url(force_refresh=probe)
    service_running = service_url is not None

    if auto_start and cli_available and not service_running:
        ensure_service_running()
        service_url = get_service_url(force_refresh=True)
        service_running = service_url is not None

    models = get_cached_models(force_refresh=probe) if service_running else []
    selected = select_model(config.foundry_model or None, models)

    if not cli_available:
        phase = "notInstalled"
        notes = "Foundry CLI is not available."
        return FoundryStatus(cli_available, False, None, [], config.foundry_model or None, None, phase, notes)
    if not service_running:
        phase = "notRunning"
        notes = "Foundry Local service is not running."
        return FoundryStatus(cli_available, False, None, [], config.foundry_model or None, None, phase, notes)
    if not models:
        phase = "noModels"
        notes = "Foundry Local is running, but no cached models were found."
        return FoundryStatus(cli_available, True, service_url, [], config.foundry_model or None, None, phase, notes)

    if not probe:
        phase = "unchecked"
        notes = f"Foundry Local service detected at {service_url}."
        return FoundryStatus(cli_available, True, service_url, models, config.foundry_model or None, selected, phase, notes)

    api_base, probe_error = probe_service(service_url or "")
    if api_base:
        return FoundryStatus(
            cli_available,
            True,
            service_url,
            models,
            config.foundry_model or None,
            selected,
            "ready",
            f"Ready at {api_base}.",
            probe={"result": "success", "apiBase": api_base},
        )
    phase = "preparing" if probe_error == "timeout" else "error"
    notes = "Foundry Local is still warming up." if probe_error == "timeout" else f"Foundry probe failed: {probe_error or 'unknown error'}"
    return FoundryStatus(
        cli_available,
        True,
        service_url,
        models,
        config.foundry_model or None,
        selected,
        phase,
        notes,
        probe={"result": probe_error or "error", "apiBase": None},
    )


def make_foundry_ready(config: AppConfig) -> FoundryStatus:
    status = foundry_status(config, probe=False, auto_start=True)
    if status.phase in {"notInstalled", "notRunning", "noModels"}:
        return status

    service_url = status.service_url or get_service_url(force_refresh=True)
    if not service_url:
        return FoundryStatus(
            status.cli_available,
            False,
            None,
            status.models,
            status.configured_model,
            status.selected_model,
            "notRunning",
            "Foundry Local service did not expose a service URL after start.",
        )

    api_base, probe_error = probe_service(service_url, timeout_s=FAST_PROBE_TIMEOUT_S)
    if api_base:
        ready = foundry_status(config, probe=True, auto_start=False)
        ready.phase = "ready"
        ready.notes = f"Ready at {api_base}."
        return ready

    sorted_candidates = sorted(status.models, key=_preferred_model_score, reverse=True)
    if status.selected_model and status.selected_model in sorted_candidates:
        sorted_candidates.remove(status.selected_model)
        sorted_candidates.insert(0, status.selected_model)
    if not sorted_candidates:
        return FoundryStatus(
            status.cli_available,
            True,
            service_url,
            status.models,
            status.configured_model,
            None,
            "noModels",
            "No usable Foundry Local model is available.",
        )

    started = time.time()
    last_error = probe_error or "timeout"
    timeout_s = SLOW_PROBE_TIMEOUT_S
    api_base = ""
    for model in sorted_candidates:
        while time.time() - started < TOTAL_WARMUP_TIMEOUT_S:
            api_base, probe_error = probe_service(service_url, timeout_s=FAST_PROBE_TIMEOUT_S)
            if api_base:
                ready, last_error = probe_chat_completion(api_base, model, timeout_s)
                if ready:
                    return FoundryStatus(
                        status.cli_available,
                        True,
                        service_url,
                        status.models,
                        status.configured_model,
                        model,
                        "ready",
                        f"Ready at {api_base}.",
                        probe={"result": "success", "apiBase": api_base},
                    )
                break
            last_error = probe_error or last_error
            time.sleep(3.0)
        timeout_s = max(timeout_s, FAST_PROBE_TIMEOUT_S)

    return FoundryStatus(
        status.cli_available,
        True,
        service_url,
        status.models,
        status.configured_model,
        sorted_candidates[0],
        "preparing" if last_error == "timeout" else "error",
        "Foundry Local is still warming up." if last_error == "timeout" else f"Foundry warmup failed: {last_error}",
        probe={"result": last_error, "apiBase": api_base or None},
    )


def resolve_foundry_api_base(config: AppConfig) -> str:
    candidates: list[str] = []
    endpoint = config.foundry_endpoint.strip()
    if endpoint:
        candidates.append(endpoint.rstrip("/"))

    service_url = get_service_url()
    if service_url:
        candidates.extend([f"{service_url}/openai/v1", f"{service_url}/v1"])

    for candidate in candidates:
        try:
            response = httpx.get(f"{candidate}/models", timeout=FAST_PROBE_TIMEOUT_S)
            if response.status_code == 200:
                return candidate
        except httpx.HTTPError:
            continue

    if endpoint:
        return endpoint.rstrip("/")
    raise TranslationError(
        "Foundry Local is not reachable. Start the service with 'foundry service start' or configure a working endpoint."
    )
