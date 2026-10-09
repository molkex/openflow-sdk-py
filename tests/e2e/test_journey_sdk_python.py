"""End-to-end user journey through the Python SDK. All HTTP mocked with respx."""
import httpx
import pytest
import respx

from openflow import (
    AsyncOpenFlow,
    AuthError,
    BadRequestError,
    OpenFlow,
    OpenFlowError,
    QuotaError,
    UpstreamError,
)
from openflow.models import ImageResult, ModelInfo, StreamChunk

from .conftest import API_KEY, IMAGE, LLM, MODELS

MSGS = [{"role": "user", "content": "hi"}]
MODEL = "gemini-3.5-flash-low"


# ───── 1. construction / env ─────

def test_explicit_key_without_env(monkeypatch):
    monkeypatch.delenv("OPENFLOW_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with OpenFlow(api_key=API_KEY) as of:
        assert of.api_key == API_KEY


def test_no_key_anywhere_raises(monkeypatch):
    monkeypatch.delenv("OPENFLOW_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(OpenFlowError):
        OpenFlow()


def test_env_key_without_explicit(monkeypatch):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_from_env")
    with OpenFlow() as of:
        assert of.api_key == "fk_from_env"


@respx.mock
def test_env_key_is_sent_on_the_wire(monkeypatch, anthropic_reply):
    monkeypatch.setenv("OPENFLOW_API_KEY", "fk_from_env")
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow() as of:
        of.chat(model=MODEL, messages=MSGS)
    assert route.calls.last.request.headers["x-api-key"] == "fk_from_env"


# ───── 2. list_models ─────

@respx.mock
def test_list_models():
    respx.get(MODELS).mock(return_value=httpx.Response(200, json={"data": [
        {"id": "gemini-3.5-flash-low", "display_name": "Flash Low", "owned_by": "google"},
        {"id": "claude-sonnet", "context_window": 200000},
    ]}))
    with OpenFlow(api_key=API_KEY) as of:
        models = of.list_models()
    assert all(isinstance(m, ModelInfo) for m in models)
    assert [m.id for m in models] == ["gemini-3.5-flash-low", "claude-sonnet"]
    assert models[0].label == "Flash Low"
    assert models[0].provider == "google"
    assert models[1].context_window == 200000


@respx.mock
def test_list_models_empty():
    respx.get(MODELS).mock(return_value=httpx.Response(200, json={"data": []}))
    with OpenFlow(api_key=API_KEY) as of:
        assert of.list_models() == []


# ───── 3. chat ─────

@respx.mock
def test_chat_happy(anthropic_reply):
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow(api_key=API_KEY) as of:
        reply = of.chat(model=MODEL, messages=MSGS)
    assert reply.text == "hello world"
    assert reply.model == MODEL
    assert reply.usage.input_tokens == 5
    assert reply.usage.output_tokens == 2
    assert reply.stop_reason == "end_turn"
    req = route.calls.last.request
    assert req.headers["x-api-key"] == API_KEY
    assert req.headers["anthropic-version"] == "2023-06-01"


@respx.mock
def test_chat_request_body(anthropic_reply):
    import json
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow(api_key=API_KEY) as of:
        of.chat(model=MODEL, messages=MSGS, system="be brief", max_tokens=64, temperature=0.2)
    body = json.loads(route.calls.last.request.content)
    assert body == {"model": MODEL, "messages": MSGS, "max_tokens": 64,
                    "system": "be brief", "temperature": 0.2}


@respx.mock
def test_chat_tool_use(anthropic_tool_reply):
    respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_tool_reply))
    with OpenFlow(api_key=API_KEY) as of:
        reply = of.chat(model=MODEL, messages=MSGS)
    assert reply.stop_reason == "tool_use"
    assert reply.tool_calls[0].name == "get_weather"
    assert reply.tool_calls[0].arguments == {"city": "Paris"}


# ───── 4. streaming ─────

@respx.mock
def test_chat_stream(anthropic_stream_sse):
    route = respx.post(LLM).mock(return_value=httpx.Response(
        200, content=anthropic_stream_sse, headers={"content-type": "text/event-stream"}))
    with OpenFlow(api_key=API_KEY) as of:
        chunks = list(of.chat_stream(model=MODEL, messages=MSGS))
    assert all(isinstance(c, StreamChunk) for c in chunks)
    assert "".join(c.text_delta for c in chunks) == "Hello world"
    assert chunks[-1].raw["type"] == "message_stop"
    assert [c.stop_reason for c in chunks if c.stop_reason] == ["end_turn"]
    import json
    assert json.loads(route.calls.last.request.content)["stream"] is True


@respx.mock
def test_chat_stream_error_status():
    respx.post(LLM).mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(AuthError):
            list(of.chat_stream(model=MODEL, messages=MSGS))


# ───── 5. account routing ─────

@respx.mock
def test_chat_account_headers(anthropic_reply):
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow(api_key=API_KEY) as of:
        of.chat(model=MODEL, messages=MSGS, account_email="x@y.com", account_tag="prod")
    h = route.calls.last.request.headers
    assert h["X-Account-Email"] == "x@y.com"
    assert h["X-Account-Tag"] == "prod"


@respx.mock
def test_chat_no_account_headers_by_default(anthropic_reply):
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow(api_key=API_KEY) as of:
        of.chat(model=MODEL, messages=MSGS)
    h = route.calls.last.request.headers
    assert "X-Account-Email" not in h
    assert "X-Account-Tag" not in h


# ───── 6. image ─────

@respx.mock
def test_generate_image_urls():
    import json
    route = respx.post(IMAGE).mock(return_value=httpx.Response(200, json={
        "job_id": "job_1", "status": "done", "urls": ["https://cdn.example/a.png"]}))
    with OpenFlow(api_key=API_KEY) as of:
        res = of.generate_image("a red fox", count=1, aspect="1:1")
    assert isinstance(res, ImageResult)
    assert res.job_id == "job_1"
    assert res.status == "done"
    assert res.urls == ["https://cdn.example/a.png"]
    req = route.calls.last.request
    assert req.headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(req.content) == {"prompt": "a red fox", "count": 1, "aspect": "1:1"}


@respx.mock
def test_generate_image_pending_job():
    respx.post(IMAGE).mock(return_value=httpx.Response(200, json={"id": "job_2"}))
    with OpenFlow(api_key=API_KEY) as of:
        res = of.generate_image("x")
    assert res.job_id == "job_2"
    assert res.status == "pending"
    assert res.urls == []


@respx.mock
def test_generate_image_single_url_and_account_headers():
    route = respx.post(IMAGE).mock(return_value=httpx.Response(200, json={
        "id": "j3", "url": "https://cdn.example/b.png"}))
    with OpenFlow(api_key=API_KEY) as of:
        res = of.generate_image("x", account_tag="farm")
    assert res.urls == ["https://cdn.example/b.png"]
    assert res.status == "done"
    assert route.calls.last.request.headers["X-Account-Tag"] == "farm"


# ───── 7. error mapping ─────

@pytest.mark.parametrize("status,exc", [
    (401, AuthError),
    (403, AuthError),
    (429, QuotaError),
    (500, UpstreamError),
    (400, BadRequestError),
    (404, BadRequestError),
])
@respx.mock
def test_error_mapping(status, exc, anthropic_reply):
    respx.post(LLM).mock(return_value=httpx.Response(status, json={"error": {"message": "boom"}}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(exc) as ei:
            of.chat(model=MODEL, messages=MSGS)
    assert ei.value.status_code == status
    assert ei.value.message == "boom"


@respx.mock
def test_error_message_from_error_object():
    respx.post(LLM).mock(return_value=httpx.Response(
        400, json={"error": {"type": "invalid_request", "message": "max_tokens too large"}}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(BadRequestError, match="max_tokens too large"):
            of.chat(model=MODEL, messages=MSGS)


@respx.mock
def test_error_fallback_message_on_non_json_body():
    respx.post(LLM).mock(return_value=httpx.Response(401, content=b""))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(AuthError) as ei:
            of.chat(model=MODEL, messages=MSGS)
    assert ei.value.status_code == 401


@respx.mock
def test_error_carries_request_id():
    respx.post(LLM).mock(return_value=httpx.Response(
        429, json={"error": {"message": "slow down"}}, headers={"x-request-id": "req_42"}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(QuotaError) as ei:
            of.chat(model=MODEL, messages=MSGS)
    assert ei.value.request_id == "req_42"
    assert "req_42" in str(ei.value)


@respx.mock
def test_500_is_not_retried():
    route = respx.post(LLM).mock(return_value=httpx.Response(500, json={"error": "x"}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(UpstreamError):
            of.chat(model=MODEL, messages=MSGS)
    assert route.call_count == 1


@pytest.mark.parametrize("status", [401, 429, 400])
@respx.mock
def test_4xx_is_not_retried(status):
    route = respx.post(LLM).mock(return_value=httpx.Response(status, json={}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(OpenFlowError):
            of.chat(model=MODEL, messages=MSGS)
    assert route.call_count == 1


# ───── 8. retry on 502/503/504 ─────

@pytest.mark.parametrize("status", [502, 503, 504])
@respx.mock
def test_retry_then_success(status, anthropic_reply):
    route = respx.post(LLM).mock(side_effect=[
        httpx.Response(status), httpx.Response(status),
        httpx.Response(200, json=anthropic_reply)])
    with OpenFlow(api_key=API_KEY) as of:
        reply = of.chat(model=MODEL, messages=MSGS)
    assert reply.text == "hello world"
    assert route.call_count == 3


@respx.mock
def test_retry_exhausted_raises_upstream():
    route = respx.post(LLM).mock(return_value=httpx.Response(502, json={"error": {"message": "bad gateway"}}))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(UpstreamError, match="bad gateway"):
            of.chat(model=MODEL, messages=MSGS)
    assert route.call_count == 3


@respx.mock
def test_retry_on_connect_error_then_success(anthropic_reply):
    route = respx.post(LLM).mock(side_effect=[
        httpx.ConnectError("down"), httpx.Response(200, json=anthropic_reply)])
    with OpenFlow(api_key=API_KEY) as of:
        assert of.chat(model=MODEL, messages=MSGS).text == "hello world"
    assert route.call_count == 2


@respx.mock
def test_connect_error_exhausted_raises_openflow_error():
    respx.post(LLM).mock(side_effect=httpx.ConnectError("down"))
    with OpenFlow(api_key=API_KEY) as of:
        with pytest.raises(OpenFlowError, match="network error"):
            of.chat(model=MODEL, messages=MSGS)


# ───── 9. context manager ─────

def test_context_manager_closes_owned_client():
    with OpenFlow(api_key=API_KEY) as of:
        inner = of._client
        assert not inner.is_closed
    assert inner.is_closed


def test_context_manager_leaves_injected_client_open():
    http = httpx.Client()
    with OpenFlow(api_key=API_KEY, http_client=http):
        pass
    assert not http.is_closed
    http.close()


# ───── async ─────

@respx.mock
async def test_async_chat_happy(anthropic_reply):
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    async with AsyncOpenFlow(api_key=API_KEY) as of:
        reply = await of.chat(model=MODEL, messages=MSGS, account_tag="prod")
    assert reply.text == "hello world"
    assert reply.usage.output_tokens == 2
    assert route.calls.last.request.headers["X-Account-Tag"] == "prod"


@respx.mock
async def test_async_chat_stream(anthropic_stream_sse):
    respx.post(LLM).mock(return_value=httpx.Response(200, content=anthropic_stream_sse))
    async with AsyncOpenFlow(api_key=API_KEY) as of:
        chunks = [c async for c in of.chat_stream(model=MODEL, messages=MSGS)]
    assert "".join(c.text_delta for c in chunks) == "Hello world"


@respx.mock
async def test_async_error_mapping():
    respx.post(LLM).mock(return_value=httpx.Response(429, json={"error": {"message": "quota"}}))
    async with AsyncOpenFlow(api_key=API_KEY) as of:
        with pytest.raises(QuotaError, match="quota"):
            await of.chat(model=MODEL, messages=MSGS)


async def test_async_context_manager_closes():
    async with AsyncOpenFlow(api_key=API_KEY) as of:
        inner = of._client
    assert inner.is_closed
