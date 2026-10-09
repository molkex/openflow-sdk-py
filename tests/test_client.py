import json
import os
import pytest
import respx
import httpx

from openflow import (
    AsyncOpenFlow,
    AuthError,
    OpenFlow,
    OpenFlowError,
    QuotaError,
)

BASE = "https://openflowmcp.com"
LLM = BASE + "/llm/v1/messages"
MODELS = BASE + "/llm/v1/models"
IMAGE = BASE + "/v1/jobs/image"
VIDEO = BASE + "/v1/jobs/video"
VOICE = BASE + "/v1/jobs/voice"
ACCTS = BASE + "/me/google/accounts"


# ───── auth / init ─────

def test_api_key_required(monkeypatch):
    monkeypatch.delenv("OPENFLOW_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(OpenFlowError):
        OpenFlow()


def test_base_url_normalized(monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_x")
    of = OpenFlow(base_url="https://openflowmcp.com/llm/")
    assert of.base_url == "https://openflowmcp.com"
    of2 = OpenFlow(base_url="https://x.y/v1")
    assert of2.base_url == "https://x.y"


# ───── chat happy ─────

@respx.mock
def test_chat_happy(anthropic_reply):
    respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow() as of:
        reply = of.chat(model="gemini-3.5-flash-low", messages=[{"role": "user", "content": "hi"}])
    assert reply.text == "hello world"
    assert reply.model == "gemini-3.5-flash-low"
    assert reply.usage.input_tokens == 5
    assert reply.usage.output_tokens == 2
    assert reply.tool_calls == []


@respx.mock
def test_chat_tool_use(anthropic_tool_reply):
    respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_tool_reply))
    with OpenFlow() as of:
        reply = of.chat(
            model="gemini-3.5-flash-low",
            messages=[{"role": "user", "content": "weather?"}],
            tools=[{"name": "get_weather", "input_schema": {}}],
        )
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].name == "get_weather"
    assert reply.tool_calls[0].arguments == {"city": "Paris"}


@respx.mock
def test_chat_passes_system_and_tools():
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json={
        "content": [{"type": "text", "text": "ok"}],
        "usage": {}, "stop_reason": "end_turn",
    }))
    with OpenFlow() as of:
        of.chat(
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            system="you are helpful",
            tools=[{"name": "t", "input_schema": {}}],
            max_tokens=42,
        )
    body = json.loads(route.calls[0].request.content)
    assert body["system"] == "you are helpful"
    assert body["tools"] == [{"name": "t", "input_schema": {}}]
    assert body["max_tokens"] == 42


@respx.mock
def test_chat_routes_account_headers():
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json={
        "content": [{"type": "text", "text": "ok"}], "usage": {},
    }))
    with OpenFlow() as of:
        of.chat(
            model="m", messages=[{"role": "user", "content": "x"}],
            account_email="farm@example.com", account_tag="prod",
        )
    req = route.calls[0].request
    assert req.headers["x-account-email"] == "farm@example.com"
    assert req.headers["x-account-tag"] == "prod"
    assert req.headers["x-api-key"].startswith("fk_")


# ───── errors ─────

@respx.mock
def test_auth_error():
    respx.post(LLM).mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
    with OpenFlow() as of:
        with pytest.raises(AuthError) as ei:
            of.chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert "bad key" in str(ei.value)


@respx.mock
def test_quota_error():
    respx.post(LLM).mock(return_value=httpx.Response(429, json={"error": {"message": "slow down"}}))
    with OpenFlow() as of:
        with pytest.raises(QuotaError):
            of.chat(model="m", messages=[{"role": "user", "content": "x"}])


# ───── streaming ─────

SSE_BODY = (
    "event: content_block_delta\n"
    "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"hel\"}}\n\n"
    "event: content_block_delta\n"
    "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"lo\"}}\n\n"
    "event: message_delta\n"
    "data: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"}}\n\n"
    "data: [DONE]\n\n"
)


@respx.mock
def test_chat_stream():
    respx.post(LLM).mock(
        return_value=httpx.Response(200, text=SSE_BODY, headers={"content-type": "text/event-stream"})
    )
    with OpenFlow() as of:
        chunks = list(of.chat_stream(model="m", messages=[{"role": "user", "content": "x"}]))
    text = "".join(c.text_delta for c in chunks)
    assert text == "hello"
    assert any(c.stop_reason == "end_turn" for c in chunks)


# ───── models / accounts ─────

@respx.mock
def test_list_models():
    respx.get(MODELS).mock(return_value=httpx.Response(200, json={
        "data": [
            {"id": "gemini-3.5-flash-low", "owned_by": "google", "display_name": "Flash Low"},
            {"id": "claude-sonnet-4-5", "owned_by": "anthropic"},
        ]
    }))
    with OpenFlow() as of:
        models = of.list_models()
    assert [m.id for m in models] == ["gemini-3.5-flash-low", "claude-sonnet-4-5"]
    assert models[0].provider == "google"


@respx.mock
def test_list_accounts():
    respx.get(ACCTS).mock(return_value=httpx.Response(200, json={
        "accounts": [
            {"id": 1, "email": "a@x", "tag": "prod", "active": True},
            {"id": 2, "email": "b@x", "tag": None, "active": False},
        ]
    }))
    with OpenFlow() as of:
        accs = of.list_accounts()
    assert accs[0].email == "a@x"
    assert accs[0].tag == "prod"
    assert accs[1].active is False


# ───── jobs ─────

@respx.mock
def test_generate_image_returns_urls():
    respx.post(IMAGE).mock(return_value=httpx.Response(200, json={
        "status": "done", "urls": ["https://cdn/x.png"], "job_id": "j1",
    }))
    with OpenFlow() as of:
        res = of.generate_image("a cat", count=1, aspect="1:1")
    assert res.urls == ["https://cdn/x.png"]
    assert res.status == "done"


@respx.mock
def test_generate_video_queued():
    respx.post(VIDEO).mock(return_value=httpx.Response(200, json={
        "status": "queued", "job_id": "jvid"
    }))
    with OpenFlow() as of:
        res = of.generate_video("rain", model="veo_3_1_r2v", duration=4)
    assert res.job_id == "jvid"
    assert res.urls == []


@respx.mock
def test_generate_voice():
    route = respx.post(VOICE).mock(return_value=httpx.Response(200, json={
        "status": "done", "url": "https://cdn/a.wav", "job_id": "jv"
    }))
    with OpenFlow() as of:
        res = of.generate_voice("hi", voice_id="v1")
    body = json.loads(route.calls[0].request.content)
    assert body == {"text": "hi", "voice_id": "v1"}
    assert res.url == "https://cdn/a.wav"


# ───── async ─────

@pytest.mark.asyncio
@respx.mock
async def test_async_chat(anthropic_reply):
    respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    async with AsyncOpenFlow() as of:
        reply = await of.chat(model="m", messages=[{"role": "user", "content": "hi"}])
    assert reply.text == "hello world"
