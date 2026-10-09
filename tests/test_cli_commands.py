"""CLI coverage tests — image/video/voice/job/doctor/accounts/chat error paths."""
from __future__ import annotations

import io
import httpx
import pytest
import respx

from openflow.cli import main

BASE = "https://openflowmcp.com"


# ───────── accounts ─────────

@respx.mock
def test_accounts_empty(capsys):
    respx.get(BASE + "/me/google/accounts").mock(
        return_value=httpx.Response(200, json={"accounts": []})
    )
    rc = main(["accounts"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no connected" in out.lower()


@respx.mock
def test_accounts_listing(capsys):
    respx.get(BASE + "/me/google/accounts").mock(
        return_value=httpx.Response(200, json={"accounts": [
            {"email": "a@x.com", "tag": "primary", "active": True},
            {"email": "b@x.com", "active": False},
        ]})
    )
    rc = main(["accounts"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "a@x.com" in out and "primary" in out
    assert "b@x.com" in out and "disabled" in out


# ───────── image ─────────

@respx.mock
def test_image_sync_result(capsys):
    respx.post(BASE + "/v1/jobs/image").mock(return_value=httpx.Response(200, json={
        "status": "done", "urls": ["https://cdn.x/i1.png"],
    }))
    rc = main(["image", "a cat"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "https://cdn.x/i1.png" in out


@respx.mock
def test_image_queued(capsys):
    respx.post(BASE + "/v1/jobs/image").mock(return_value=httpx.Response(200, json={
        "status": "pending", "job_id": "job_42",
    }))
    rc = main(["image", "cat"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "job_42" in out and "poll" in out


@respx.mock
def test_image_upstream_error(capsys):
    respx.post(BASE + "/v1/jobs/image").mock(return_value=httpx.Response(502, json={
        "error": {"message": "bad gateway"},
    }))
    rc = main(["image", "cat"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error" in err.lower()


def test_image_requires_prompt(capsys):
    # argparse requires at least one positional for "image"
    with pytest.raises(SystemExit):
        main(["image"])


# ───────── video ─────────

@respx.mock
def test_video_queued(capsys):
    respx.post(BASE + "/v1/jobs/video").mock(return_value=httpx.Response(200, json={
        "status": "pending", "job_id": "vid_1",
    }))
    rc = main(["video", "sunset"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "vid_1" in out


@respx.mock
def test_video_done_with_url(capsys):
    respx.post(BASE + "/v1/jobs/video").mock(return_value=httpx.Response(200, json={
        "status": "done", "url": "https://cdn.x/v.mp4",
    }))
    rc = main(["video", "surf"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "v.mp4" in out


@respx.mock
def test_video_auth_error(capsys):
    respx.post(BASE + "/v1/jobs/video").mock(return_value=httpx.Response(401, json={
        "error": {"message": "invalid key"},
    }))
    rc = main(["video", "x"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "invalid key" in err


# ───────── voice ─────────

@respx.mock
def test_voice_queued(capsys):
    respx.post(BASE + "/v1/jobs/voice").mock(return_value=httpx.Response(200, json={
        "job_id": "voice_1",
    }))
    rc = main(["voice", "hello world"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "voice_1" in out


@respx.mock
def test_voice_done(capsys):
    respx.post(BASE + "/v1/jobs/voice").mock(return_value=httpx.Response(200, json={
        "url": "https://cdn.x/v.wav",
    }))
    rc = main(["voice", "hi"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "v.wav" in out


# ───────── job ─────────

@respx.mock
def test_job_check(capsys):
    respx.get(BASE + "/v1/jobs/abc").mock(return_value=httpx.Response(200, json={
        "job_id": "abc", "status": "done",
    }))
    rc = main(["job", "abc"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"status": "done"' in out


# ───────── doctor ─────────

@respx.mock
def test_doctor_all_ok(capsys):
    respx.get(BASE + "/me/llm-status").mock(return_value=httpx.Response(200, json={
        "plan": "pro", "google_connected": True, "quota": {"left": 100},
    }))
    respx.get(BASE + "/llm/v1/models").mock(return_value=httpx.Response(200, json={
        "data": [{"id": "m1"}]
    }))
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[OK]" in out
    assert "pro" in out


@respx.mock
def test_doctor_google_missing(capsys):
    respx.get(BASE + "/me/llm-status").mock(return_value=httpx.Response(200, json={
        "plan": "free",
    }))
    respx.get(BASE + "/llm/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out


@respx.mock
def test_doctor_auth_fail(capsys):
    respx.get(BASE + "/me/llm-status").mock(return_value=httpx.Response(401, json={
        "error": {"message": "nope"},
    }))
    respx.get(BASE + "/llm/v1/models").mock(return_value=httpx.Response(401, json={
        "error": {"message": "nope"},
    }))
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out


def test_doctor_no_key(capsys, monkeypatch):
    monkeypatch.delenv("OPENFLOW_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "API key" in out


# ───────── chat error / streaming ─────────

@respx.mock
def test_chat_error_exit_code(capsys):
    respx.post(BASE + "/llm/v1/messages").mock(return_value=httpx.Response(429, json={
        "error": {"message": "slow down"},
    }))
    rc = main(["chat", "hi"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "slow down" in err


def test_chat_requires_prompt(capsys):
    rc = main(["chat"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "usage" in err.lower()


@respx.mock
def test_chat_stream_mode(capsys):
    sse = (
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hel"}}\n\n'
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}\n\n'
        b'data: [DONE]\n\n'
    )
    respx.post(BASE + "/llm/v1/messages").mock(
        return_value=httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
    )
    rc = main(["chat", "--stream", "-m", "m", "hey"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "hello" in out


@respx.mock
def test_chat_json_output(capsys):
    respx.post(BASE + "/llm/v1/messages").mock(return_value=httpx.Response(200, json={
        "content": [{"type": "text", "text": "ok"}],
        "usage": {}, "stop_reason": "end_turn",
    }))
    rc = main(["chat", "--json", "-m", "m", "hey"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"content"' in out


# ───────── version / top-level ─────────

def test_toplevel_version_flag(capsys):
    rc = main(["-V"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "openflow" in out
