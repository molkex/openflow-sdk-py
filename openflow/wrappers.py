"""Thin wrappers around third-party coding CLIs.

Each wrapper reads OPENFLOW_API_KEY, maps it into the provider-standard
environment variable, points the provider base URL at openflowmcp.com and
exec()s the original CLI. Zero mention of the upstream provider in the UX.

Usage:
    export OPENFLOW_API_KEY=fk_...
    openflow-code "fix the bug in main.py"
    openflow-cursor
    openflow-aider path/to/file
    openflow-codex "..."
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_BASE = os.environ.get("OPENFLOW_BASE_URL", "https://openflowmcp.com/llm")


def _die(msg: str, code: int = 1) -> None:
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(code)


def _key() -> str:
    k = os.environ.get("OPENFLOW_API_KEY", "").strip()
    if not k:
        _die(
            "openFlow: OPENFLOW_API_KEY is not set.\n"
            "Get a key at https://openflowmcp.com and run:\n"
            "  export OPENFLOW_API_KEY=fk_...\n"
        )
    return k


def _need(cli: str, install_hint: str) -> str:
    path = shutil.which(cli)
    if not path:
        _die(f"openFlow: '{cli}' is not installed.\n{install_hint}\n")
    return path


def _exec(path: str, argv: list[str], env: dict[str, str]) -> None:
    merged = os.environ.copy()
    merged.update(env)
    try:
        os.execvpe(path, [path, *argv], merged)
    except OSError as e:
        _die(f"openFlow: failed to launch {path}: {e}")


def code_main() -> None:
    """openflow-code — Claude Code CLI routed through openFlow."""
    key = _key()
    cli = _need(
        "claude",
        "Install the Claude Code CLI first: https://docs.anthropic.com/en/docs/claude-code/overview",
    )
    _exec(
        cli,
        sys.argv[1:],
        {
            "ANTHROPIC_API_KEY": key,
            "ANTHROPIC_BASE_URL": DEFAULT_BASE,
            # Belt-and-braces: some tools look for AUTH_TOKEN first.
            "ANTHROPIC_AUTH_TOKEN": key,
        },
    )


def aider_main() -> None:
    """openflow-aider — aider routed through openFlow (OpenAI-compatible)."""
    key = _key()
    cli = _need(
        "aider",
        "Install aider first: pip install aider-chat (https://aider.chat)",
    )
    _exec(
        cli,
        sys.argv[1:],
        {
            "OPENAI_API_KEY": key,
            "OPENAI_API_BASE": DEFAULT_BASE,
            "OPENAI_BASE_URL": DEFAULT_BASE,
        },
    )


def codex_main() -> None:
    """openflow-codex — OpenAI Codex CLI routed through openFlow."""
    key = _key()
    cli = _need(
        "codex",
        "Install OpenAI Codex CLI first: https://github.com/openai/codex",
    )
    _exec(
        cli,
        sys.argv[1:],
        {
            "OPENAI_API_KEY": key,
            "OPENAI_BASE_URL": DEFAULT_BASE,
            "OPENAI_API_BASE": DEFAULT_BASE,
        },
    )


def cursor_main() -> None:
    """openflow-cursor — write Cursor MCP config pointing at openFlow.

    Cursor stores MCP configuration in ~/.cursor/mcp.json. We append (or merge)
    an entry so Cursor talks to openflowmcp.com. Does NOT launch Cursor itself.
    """
    key = _key()
    cfg_dir = Path.home() / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "mcp.json"

    base = DEFAULT_BASE
    entry = {
        "openflow": {
            "url": base.rstrip("/").rsplit("/llm", 1)[0] + "/mcp",
            "headers": {"Authorization": f"Bearer {key}"},
        }
    }

    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text() or "{}")
            if not isinstance(data, dict):
                data = {}
        except json.JSONDecodeError:
            backup = cfg_path.with_suffix(".json.bak")
            cfg_path.rename(backup)
            sys.stderr.write(
                f"openFlow: existing {cfg_path} was not valid JSON; backed up to {backup}\n"
            )
            data = {}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers.update(entry)
    data["mcpServers"] = servers

    cfg_path.write_text(json.dumps(data, indent=2) + "\n")
    try:
        cfg_path.chmod(0o600)
    except OSError:
        pass
    print(f"openFlow: wrote {cfg_path}")
    print("Restart Cursor and openFlow will appear as an MCP server.")
