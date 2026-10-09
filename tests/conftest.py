import os
import pytest

os.environ.setdefault("OPENFLOW_API_KEY", "fk_test_key_1234567890")


@pytest.fixture
def anthropic_reply():
    return {
        "id": "msg_01",
        "model": "gemini-3.5-flash-low",
        "role": "assistant",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "hello world"}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }


@pytest.fixture
def anthropic_tool_reply():
    return {
        "id": "msg_02",
        "model": "gemini-3.5-flash-low",
        "role": "assistant",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "calling"},
            {
                "type": "tool_use",
                "id": "tool_1",
                "name": "get_weather",
                "input": {"city": "Paris"},
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }
