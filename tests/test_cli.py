import httpx
import respx

from openflow.cli import main

BASE = "https://openflowmcp.com"


def test_version(capsys):
    rc = main(["version"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "openflow" in out


def test_config(capsys, monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_abcdef1234")
    rc = main(["config"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "fk_a" in out and "1234" in out
    assert "openflowmcp.com" in out


@respx.mock
def test_chat_oneshot(capsys):
    respx.post(BASE + "/llm/v1/messages").mock(return_value=httpx.Response(200, json={
        "content": [{"type": "text", "text": "answer"}],
        "usage": {}, "stop_reason": "end_turn",
    }))
    rc = main(["chat", "-m", "m", "hello"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "answer" in out


@respx.mock
def test_models_cmd(capsys):
    respx.get(BASE + "/llm/v1/models").mock(return_value=httpx.Response(200, json={
        "data": [{"id": "foo-model", "owned_by": "x"}]
    }))
    rc = main(["models"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "foo-model" in out
