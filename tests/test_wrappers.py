"""Tests for the thin CLI wrappers.

They never actually exec; we patch os.execvpe and shutil.which.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from openflow import wrappers


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Fresh env for every test.
    for k in (
        "OPENFLOW_API_KEY",
        "OPENFLOW_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(wrappers, "DEFAULT_BASE", "https://openflowmcp.com/llm")
    yield


def _capture_exec(monkeypatch):
    seen = {}

    def fake_exec(path, argv, env):
        seen["path"] = path
        seen["argv"] = argv
        seen["env"] = env

    monkeypatch.setattr(wrappers, "_exec", fake_exec)
    return seen


def test_code_requires_key(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["openflow-code", "hi"])
    with pytest.raises(SystemExit) as excinfo:
        wrappers.code_main()
    assert excinfo.value.code == 1


def test_code_requires_claude_installed(monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_test")
    monkeypatch.setattr(sys, "argv", ["openflow-code", "hi"])
    monkeypatch.setattr(wrappers.shutil, "which", lambda _n: None)
    with pytest.raises(SystemExit):
        wrappers.code_main()


def test_code_sets_anthropic_env(monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_abc")
    monkeypatch.setattr(sys, "argv", ["openflow-code", "do", "it"])
    monkeypatch.setattr(wrappers.shutil, "which", lambda n: "/usr/bin/" + n)
    seen = _capture_exec(monkeypatch)
    wrappers.code_main()
    assert seen["path"] == "/usr/bin/claude"
    assert seen["argv"] == ["do", "it"]
    assert seen["env"]["ANTHROPIC_API_KEY"] == "fk_abc"
    assert seen["env"]["ANTHROPIC_AUTH_TOKEN"] == "fk_abc"
    assert seen["env"]["ANTHROPIC_BASE_URL"] == "https://openflowmcp.com/llm"


def test_aider_sets_openai_env(monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_x")
    monkeypatch.setattr(sys, "argv", ["openflow-aider", "file.py"])
    monkeypatch.setattr(wrappers.shutil, "which", lambda n: "/opt/" + n)
    seen = _capture_exec(monkeypatch)
    wrappers.aider_main()
    assert seen["path"] == "/opt/aider"
    assert seen["env"]["OPENAI_API_KEY"] == "fk_x"
    assert seen["env"]["OPENAI_BASE_URL"] == "https://openflowmcp.com/llm"
    assert seen["env"]["OPENAI_API_BASE"] == "https://openflowmcp.com/llm"


def test_codex_sets_openai_env(monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_c")
    monkeypatch.setattr(sys, "argv", ["openflow-codex"])
    monkeypatch.setattr(wrappers.shutil, "which", lambda n: "/opt/" + n)
    seen = _capture_exec(monkeypatch)
    wrappers.codex_main()
    assert seen["env"]["OPENAI_API_KEY"] == "fk_c"


def test_cursor_writes_mcp_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_cursor")
    wrappers.cursor_main()
    cfg = Path(os.environ["HOME"]) / ".cursor" / "mcp.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert "mcpServers" in data
    assert "openflow" in data["mcpServers"]
    assert data["mcpServers"]["openflow"]["url"].endswith("/mcp")
    assert "fk_cursor" in data["mcpServers"]["openflow"]["headers"]["Authorization"]


def test_cursor_merges_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_cursor")
    cfg = Path(os.environ["HOME"]) / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"mcpServers": {"other": {"url": "https://x"}}}))
    wrappers.cursor_main()
    data = json.loads(cfg.read_text())
    assert "other" in data["mcpServers"]
    assert "openflow" in data["mcpServers"]
