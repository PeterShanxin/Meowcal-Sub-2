"""Check the declared IPC boundary; native Windows tests exercise Tauri enforcement."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

SHELL = Path(__file__).resolve().parents[1] / "src-tauri"
LOOPBACK_ORIGINS = {"http://127.0.0.1:*", "http://localhost:*"}


def shell_permissions() -> tuple[list[dict], dict[str, dict]]:
    capabilities = [
        json.loads(path.read_text()) for path in (SHELL / "capabilities").glob("*.json")
    ]
    permissions = {}
    for path in (SHELL / "permissions").rglob("*.toml"):
        document = tomllib.loads(path.read_text())
        # New permission indirection needs explicit review of this boundary check.
        assert not document.get("set") and not document.get("default")
        for permission in document.get("permission", []):
            assert permission["identifier"] not in permissions
            permissions[permission["identifier"]] = permission.get("commands", {})
    return capabilities, permissions


def command_grants(
    capabilities: list[dict], permissions: dict[str, dict], command: str
) -> list[dict]:
    grants = []
    for capability in capabilities:
        for reference in capability.get("permissions", []):
            identifier = reference if isinstance(reference, str) else reference["identifier"]
            if identifier.startswith("core:"):
                continue
            commands = permissions[identifier]
            if command in commands.get("allow", []):
                grants.append(capability)
    return grants


@pytest.mark.parametrize(
    ("window", "command", "remote"),
    [
        ("main", "open_area_selector", True),
        ("main", "enter_live_mode", True),
        ("main", "exit_live_mode", True),
        ("main", "stop_translation", True),
        ("main", "get_api_base", True),
        ("selector", "set_capture_region", False),
        ("selector", "cancel_area_selector", False),
        ("selector", "get_capture_region", False),
        ("selector", "get_selector_backdrop", False),
        ("overlay", "set_overlay_height", True),
    ],
)
def test_window_can_perform_its_actions_without_granting_other_windows_or_origins(
    window: str, command: str, remote: bool
) -> None:
    capabilities, permissions = shell_permissions()
    grants = command_grants(capabilities, permissions, command)
    assert grants, f"{window} cannot invoke required command {command}"
    assert all(command not in rules.get("deny", []) for rules in permissions.values())
    for grant in grants:
        assert set(grant.get("windows", [])) == {window}, f"{command} reaches another window"
        # Tauri matches either a window or webview selector; another selector can widen access.
        assert not grant.get("webviews"), f"{command} also grants access by webview label"
        urls = set(grant.get("remote", {}).get("urls", []))
        if remote:
            assert urls and urls <= LOOPBACK_ORIGINS, f"{command} is not confined to loopback"
        else:
            assert grant.get("local", True), f"The bundled {window} cannot invoke {command}"
            assert not urls, f"Remote content can invoke {command}"


def test_api_token_is_not_exposed_to_any_frontend() -> None:
    _, permissions = shell_permissions()
    assert all("get_api_token" not in rules.get("allow", []) for rules in permissions.values())
