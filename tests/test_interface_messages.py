"""Backend text the studio shows must be in the studio's translation catalog.

The studio translates backend messages by their English wording, so a new or
reworded message would silently stay English in the Chinese interface. Values
formatted into a message read as `{}` on both sides.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src/meocosub2"
I18N = PACKAGE / "overlay/ui/src/i18n"

# Modules whose messages reach the studio as progress, warnings, API errors,
# engine status, language names or title chips. Core protocol and process
# failures are not here: the studio shows those as technical details.
VIEWER_FACING = (
    "capture.py",
    "languages.py",
    "subtitles.py",
    "translator.py",
    "semantic.py",
    "engine/__init__.py",
    "engine/install.py",
    "engine/manifest.py",
    "engine/runtime.py",
    "opensubtitles/client.py",
    "overlay/controller.py",
    "overlay/subtitle_editor.py",
    "subtitle_sources/aggregator.py",
    "subtitle_sources/assrt.py",
    "subtitle_sources/cache_paths.py",
    "subtitle_sources/subdl.py",
    "subtitle_sources/utils.py",
)

MESSAGE_KEYWORDS = {"message", "label", "warning", "warning_message", "reason"}
# Callee name -> index of its positional message argument.
MESSAGE_ARGUMENTS = {
    "_set_error": 0,
    "_report": 1,
    "EngineStatus": 1,
    "OcrResolution": 2,
    "LanguageOption": 1,
}
MESSAGE_FUNCTIONS = re.compile(r"_message$|_warning$|^_wordless_failure$")


def _template(node: ast.AST) -> list[str]:
    """The message text a node can produce, with formatted values as `{}`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts = [part.value if isinstance(part, ast.Constant) else "{}" for part in node.values]
        return ["".join(str(part) for part in parts)]
    if isinstance(node, ast.IfExp):
        return _template(node.body) + _template(node.orelse)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _template(node.left), _template(node.right)
        return [a + b for a in left or ["{}"] for b in right or ["{}"]]
    return []


def _is_prose(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text)) and (" " in text.strip() or text.endswith("."))


def messages_in(source: str) -> set[str]:
    """Message templates a viewer-facing module can show."""
    found: list[ast.AST] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
            found.append(node.exc.args[0])
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            found += [kw.value for kw in node.keywords if kw.arg in MESSAGE_KEYWORDS]
            index = MESSAGE_ARGUMENTS.get(name)
            if index is not None and len(node.args) > index:
                found.append(node.args[index])
            receiver = getattr(node.func, "value", None)
            if name == "append" and re.search(r"warning|rewritten", getattr(receiver, "id", "")):
                found += node.args
        elif isinstance(node, ast.Assign):
            targets = " ".join(ast.unparse(target) for target in node.targets)
            if re.search(r"message|warning|^fallback$", targets, re.IGNORECASE):
                found.append(node.value)
        elif isinstance(node, ast.Dict):
            found += [
                value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and key.value in {"message", "reason"}
            ]
        elif isinstance(node, ast.FunctionDef) and MESSAGE_FUNCTIONS.search(node.name):
            found += [
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Return) and child.value is not None
            ]
    return {text for node in found for text in _template(node) if _is_prose(text)}


def _canonical(text: str) -> str:
    return re.sub(r"\{\w*\}", "{}", text)


def uncatalogued(source: str, catalog: set[str]) -> list[str]:
    known = {_canonical(key) for key in catalog}
    return sorted(text for text in messages_in(source) if _canonical(text) not in known)


def test_every_viewer_facing_message_is_catalogued() -> None:
    # Language names are looked up as interface text; everything else the
    # backend writes is a message.
    catalog = {
        key
        for name in ("messages-zh.json", "en-zh.json")
        for key in json.loads((I18N / name).read_text(encoding="utf-8"))
    }
    missing = [
        f"{name}: {text!r}"
        for name in VIEWER_FACING
        for text in uncatalogued((PACKAGE / name).read_text(encoding="utf-8"), catalog)
    ]
    assert missing == []


def test_a_new_message_fails_until_it_is_catalogued() -> None:
    source = """
def prepare(name):
    raise ValueError(f"Could not prepare {name}.")

def status():
    return EngineStatus("ready", "Engine ready.")

def _search_warning(code):
    return "ok" if code else f"{code} failed twice."
"""
    assert uncatalogued(source, set()) == [
        "Could not prepare {}.",
        "Engine ready.",
        "{} failed twice.",
    ]
    catalog = {"Could not prepare {title}.", "Engine ready.", "{provider} failed twice."}
    assert uncatalogued(source, catalog) == []
