import json

import pytest

BASE = "https://openflowmcp.com"
LLM = BASE + "/llm/v1/messages"
MODELS = BASE + "/llm/v1/models"
IMAGE = BASE + "/v1/jobs/image"
VIDEO = BASE + "/v1/jobs/video"
VOICE = BASE + "/v1/jobs/voice"
ACCTS = BASE + "/me/google/accounts"

API_KEY = "fk_e2e_key_1234567890"


@pytest.fixture
def base_url():
    return BASE


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Retry back-off is irrelevant for mocked tests; skip real sleeping."""
    monkeypatch.setattr("openflow.client.time.sleep", lambda _s: None)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@pytest.fixture
def anthropic_stream_sse() -> bytes:
    """Anthropic-style SSE stream that spells out 'Hello world'."""
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_s1", "type": "message", "role": "assistant",
            "model": "gemini-3.5-flash-low", "content": [],
            "usage": {"input_tokens": 5, "output_tokens": 0}}}),
        ("ping", {"type": "ping"}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "Hello "}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "world"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 2}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(_sse(e, d) for e, d in events).encode()
