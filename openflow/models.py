"""Lightweight dataclasses returned from the SDK. No pydantic — zero extra deps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Usage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    @classmethod
    def from_raw(cls, raw: Optional[Dict[str, Any]]) -> "Usage":
        if not isinstance(raw, dict):
            return cls()
        # Anthropic shape
        if "input_tokens" in raw or "output_tokens" in raw:
            it = raw.get("input_tokens")
            ot = raw.get("output_tokens")
            tot = (it or 0) + (ot or 0) if (it is not None or ot is not None) else None
            return cls(input_tokens=it, output_tokens=ot, total_tokens=tot)
        # OpenAI / Gemini shape
        it = raw.get("prompt_tokens") or raw.get("promptTokenCount")
        ot = raw.get("completion_tokens") or raw.get("candidatesTokenCount")
        tot = raw.get("total_tokens") or raw.get("totalTokenCount")
        return cls(input_tokens=it, output_tokens=ot, total_tokens=tot)


@dataclass
class ToolCall:
    id: Optional[str]
    name: str
    arguments: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatReply:
    text: str
    tool_calls: List[ToolCall]
    stop_reason: Optional[str]
    model: Optional[str]
    usage: Usage
    raw: Dict[str, Any]


@dataclass
class StreamChunk:
    text_delta: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    stop_reason: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelInfo:
    id: str
    label: Optional[str] = None
    provider: Optional[str] = None
    context_window: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountInfo:
    id: Optional[str]
    email: str
    tag: Optional[str] = None
    active: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    job_id: Optional[str]
    status: str
    urls: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    job_id: Optional[str]
    status: str
    urls: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceResult:
    job_id: Optional[str]
    status: str
    url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def parse_chat_reply(raw: Dict[str, Any]) -> ChatReply:
    """Parse a non-streaming chat response in Anthropic Messages shape.

    OmniRoute's Anthropic-compat endpoint is the canonical shape. We also
    tolerate the OpenAI chat.completions shape when the user hit `/llm/v1`.
    """
    # OpenAI shape
    if "choices" in raw and isinstance(raw["choices"], list) and raw["choices"]:
        choice = raw["choices"][0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        text = message.get("content") or ""
        if isinstance(text, list):  # content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        tool_calls: List[ToolCall] = []
        for tc in message.get("tool_calls", []) or []:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            args = fn.get("arguments")
            if isinstance(args, str):
                import json as _json
                try:
                    args = _json.loads(args)
                except Exception:
                    args = {"_raw": args}
            tool_calls.append(ToolCall(id=tc.get("id"), name=fn.get("name", ""), arguments=args or {}, raw=tc))
        return ChatReply(
            text=text or "",
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason"),
            model=raw.get("model"),
            usage=Usage.from_raw(raw.get("usage")),
            raw=raw,
        )
    # Anthropic shape
    content = raw.get("content", [])
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id"),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}) or {},
                        raw=block,
                    )
                )
    return ChatReply(
        text="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=raw.get("stop_reason"),
        model=raw.get("model"),
        usage=Usage.from_raw(raw.get("usage")),
        raw=raw,
    )
