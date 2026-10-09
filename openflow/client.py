"""openflow — thin sync+async client for openflowmcp.com.

Design: the LLM endpoints at /llm are Anthropic-Messages-compatible by default
(same shape OmniRoute speaks). The Flow REST endpoints at /v1 are the openFlow
job APIs (image, video, voice). Account routing goes through X-Account-Email /
X-Account-Tag headers.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Any, AsyncIterator, Dict, Iterable, Iterator, List, Mapping, Optional

import httpx

from ._version import __version__
from .errors import OpenFlowError, error_from_response
from .models import (
    AccountInfo,
    ChatReply,
    ImageResult,
    ModelInfo,
    StreamChunk,
    VideoResult,
    VoiceResult,
    parse_chat_reply,
)

DEFAULT_BASE_URL = "https://openflowmcp.com"
LLM_PATH = "/llm"
FLOW_PATH = "/v1"
DEFAULT_TIMEOUT = 120.0
RETRY_STATUSES = {502, 503, 504}
MAX_RETRIES = 3


def _ua() -> str:
    return f"openflow-sdk-py/{__version__} httpx/{httpx.__version__}"


def _resolve_key(explicit: Optional[str]) -> str:
    key = explicit or os.environ.get("OPENFLOW_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise OpenFlowError(
            "OPENFLOW_API_KEY is not set. Pass api_key=... or export OPENFLOW_API_KEY=fk_..."
        )
    return key


def _resolve_base(explicit: Optional[str]) -> str:
    base = (explicit or os.environ.get("OPENFLOW_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    # Normalize common forms: user may pass full /llm already.
    if base.endswith("/llm"):
        base = base[:-4]
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _route_headers(account_email: Optional[str], account_tag: Optional[str]) -> Dict[str, str]:
    h: Dict[str, str] = {}
    if account_email:
        h["X-Account-Email"] = account_email
    if account_tag:
        h["X-Account-Tag"] = account_tag
    return h


def _anthropic_body(
    model: str,
    messages: List[Dict[str, Any]],
    system: Optional[str],
    max_tokens: int,
    tools: Optional[List[Dict[str, Any]]],
    stream: bool,
    extra: Mapping[str, Any],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
    if stream:
        body["stream"] = True
    for k, v in extra.items():
        if v is not None and k not in body:
            body[k] = v
    return body


def _llm_headers(api_key: str) -> Dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "user-agent": _ua(),
    }


def _flow_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
        "user-agent": _ua(),
    }


def _parse_sse_event(buffer: str) -> Optional[Dict[str, Any]]:
    """Parse one SSE event block (data: ...) into a dict, or None if blank/[DONE]."""
    data_lines = [ln[5:].lstrip() for ln in buffer.splitlines() if ln.startswith("data:")]
    if not data_lines:
        return None
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def _chunk_from_anthropic_event(ev: Dict[str, Any]) -> StreamChunk:
    etype = ev.get("type")
    if etype == "content_block_delta":
        delta = ev.get("delta") or {}
        if delta.get("type") == "text_delta":
            return StreamChunk(text_delta=delta.get("text", ""), raw=ev)
        if delta.get("type") == "input_json_delta":
            return StreamChunk(tool_call_delta={"partial_json": delta.get("partial_json", "")}, raw=ev)
    if etype == "content_block_start":
        block = ev.get("content_block") or {}
        if block.get("type") == "tool_use":
            return StreamChunk(tool_call_delta={"start": block}, raw=ev)
    if etype == "message_delta":
        return StreamChunk(stop_reason=(ev.get("delta") or {}).get("stop_reason"), raw=ev)
    return StreamChunk(raw=ev)


class _BaseClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = _resolve_key(api_key)
        self.base_url = _resolve_base(base_url)
        self.timeout = timeout

    @property
    def llm_url(self) -> str:
        return self.base_url + LLM_PATH

    @property
    def flow_url(self) -> str:
        return self.base_url + FLOW_PATH


class OpenFlow(_BaseClient):
    """Synchronous client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def __enter__(self) -> "OpenFlow":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ───────── low level ─────────

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        params: Optional[Mapping[str, Any]] = None,
    ) -> httpx.Response:
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                req = self._client.build_request(
                    method, url, headers=headers, json=json_body, params=params
                )
                resp = self._client.send(req, stream=stream)
                if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES - 1:
                    resp.close()
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                if resp.status_code >= 400 and not stream:
                    body = _safe_json(resp)
                    raise error_from_response(resp.status_code, body, resp.headers.get("x-request-id"))
                if resp.status_code >= 400 and stream:
                    body = _safe_json(resp)
                    resp.close()
                    raise error_from_response(resp.status_code, body, resp.headers.get("x-request-id"))
                return resp
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise OpenFlowError(f"network error: {e}") from e
        raise OpenFlowError(f"request failed: {last_err}")

    # ───────── LLM chat ─────────

    def chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> ChatReply:
        body = _anthropic_body(model, messages, system, max_tokens, tools, False, extra)
        headers = {**_llm_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = self._request("POST", self.llm_url + "/v1/messages", headers=headers, json_body=body)
        return parse_chat_reply(resp.json())

    def chat_stream(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> Iterator[StreamChunk]:
        body = _anthropic_body(model, messages, system, max_tokens, tools, True, extra)
        headers = {**_llm_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = self._request(
            "POST", self.llm_url + "/v1/messages", headers=headers, json_body=body, stream=True
        )
        try:
            buf: List[str] = []
            for line in resp.iter_lines():
                if line == "":
                    if buf:
                        ev = _parse_sse_event("\n".join(buf))
                        buf = []
                        if ev:
                            yield _chunk_from_anthropic_event(ev)
                    continue
                buf.append(line)
            if buf:
                ev = _parse_sse_event("\n".join(buf))
                if ev:
                    yield _chunk_from_anthropic_event(ev)
        finally:
            resp.close()

    # ───────── Models / accounts ─────────

    def list_models(self) -> List[ModelInfo]:
        headers = _llm_headers(self.api_key)
        resp = self._request("GET", self.llm_url + "/v1/models", headers=headers)
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        rows = rows or []
        out: List[ModelInfo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                ModelInfo(
                    id=row.get("id") or row.get("model") or "",
                    label=row.get("display_name") or row.get("label"),
                    provider=row.get("provider") or row.get("owned_by"),
                    context_window=row.get("context_window") or row.get("context_length"),
                    raw=row,
                )
            )
        return out

    def list_accounts(self) -> List[AccountInfo]:
        headers = _flow_headers(self.api_key)
        resp = self._request("GET", self.base_url + "/me/google/accounts", headers=headers)
        data = resp.json()
        rows = data.get("accounts") if isinstance(data, dict) else data
        rows = rows or []
        out: List[AccountInfo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                AccountInfo(
                    id=str(row.get("id")) if row.get("id") is not None else None,
                    email=row.get("email") or "",
                    tag=row.get("tag"),
                    active=bool(row.get("active", True)),
                    raw=row,
                )
            )
        return out

    # ───────── Flow jobs ─────────

    def generate_image(
        self,
        prompt: str,
        *,
        count: int = 1,
        aspect: str = "16:9",
        model: Optional[str] = None,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> ImageResult:
        body = {"prompt": prompt, "count": count, "aspect": aspect}
        if model:
            body["model"] = model
        for k, v in extra.items():
            if v is not None:
                body[k] = v
        headers = {**_flow_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = self._request("POST", self.flow_url + "/jobs/image", headers=headers, json_body=body)
        return _parse_image(resp.json())

    def generate_video(
        self,
        prompt: str,
        *,
        model: str = "veo_3_1_r2v",
        duration: int = 4,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> VideoResult:
        body: Dict[str, Any] = {"prompt": prompt, "model": model, "duration": duration}
        for k, v in extra.items():
            if v is not None:
                body[k] = v
        headers = {**_flow_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = self._request("POST", self.flow_url + "/jobs/video", headers=headers, json_body=body)
        return _parse_video(resp.json())

    def generate_voice(
        self,
        text: str,
        *,
        voice_id: Optional[str] = None,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> VoiceResult:
        body: Dict[str, Any] = {"text": text}
        if voice_id:
            body["voice_id"] = voice_id
        for k, v in extra.items():
            if v is not None:
                body[k] = v
        headers = {**_flow_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = self._request("POST", self.flow_url + "/jobs/voice", headers=headers, json_body=body)
        return _parse_voice(resp.json())

    def check_job(self, job_id: str) -> Dict[str, Any]:
        headers = _flow_headers(self.api_key)
        resp = self._request("GET", f"{self.flow_url}/jobs/{job_id}", headers=headers)
        return resp.json()

    # ───────── Status ─────────

    def status(self) -> Dict[str, Any]:
        """Return /me/llm-status — plan, quota, is-google-connected."""
        headers = _flow_headers(self.api_key)
        resp = self._request("GET", self.base_url + "/me/llm-status", headers=headers)
        return resp.json()


class AsyncOpenFlow(_BaseClient):
    """Asynchronous client with the same surface as :class:`OpenFlow`."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = http_client is None

    async def __aenter__(self) -> "AsyncOpenFlow":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        params: Optional[Mapping[str, Any]] = None,
    ) -> httpx.Response:
        import asyncio

        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                req = self._client.build_request(
                    method, url, headers=headers, json=json_body, params=params
                )
                resp = await self._client.send(req, stream=stream)
                if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES - 1:
                    await resp.aclose()
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                if resp.status_code >= 400:
                    body = _safe_json(resp)
                    if stream:
                        await resp.aclose()
                    raise error_from_response(resp.status_code, body, resp.headers.get("x-request-id"))
                return resp
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise OpenFlowError(f"network error: {e}") from e
        raise OpenFlowError(f"request failed: {last_err}")

    async def chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> ChatReply:
        body = _anthropic_body(model, messages, system, max_tokens, tools, False, extra)
        headers = {**_llm_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = await self._request("POST", self.llm_url + "/v1/messages", headers=headers, json_body=body)
        return parse_chat_reply(resp.json())

    async def chat_stream(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        account_email: Optional[str] = None,
        account_tag: Optional[str] = None,
        **extra: Any,
    ) -> AsyncIterator[StreamChunk]:
        body = _anthropic_body(model, messages, system, max_tokens, tools, True, extra)
        headers = {**_llm_headers(self.api_key), **_route_headers(account_email, account_tag)}
        resp = await self._request(
            "POST", self.llm_url + "/v1/messages", headers=headers, json_body=body, stream=True
        )
        try:
            buf: List[str] = []
            async for line in resp.aiter_lines():
                if line == "":
                    if buf:
                        ev = _parse_sse_event("\n".join(buf))
                        buf = []
                        if ev:
                            yield _chunk_from_anthropic_event(ev)
                    continue
                buf.append(line)
            if buf:
                ev = _parse_sse_event("\n".join(buf))
                if ev:
                    yield _chunk_from_anthropic_event(ev)
        finally:
            await resp.aclose()


# ───────── helpers ─────────

def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        try:
            return resp.text
        except Exception:
            return None


def _parse_image(raw: Dict[str, Any]) -> ImageResult:
    urls: List[str] = []
    if isinstance(raw.get("urls"), list):
        urls = [u for u in raw["urls"] if isinstance(u, str)]
    elif isinstance(raw.get("url"), str):
        urls = [raw["url"]]
    elif isinstance(raw.get("result"), dict) and isinstance(raw["result"].get("urls"), list):
        urls = [u for u in raw["result"]["urls"] if isinstance(u, str)]
    return ImageResult(
        job_id=raw.get("job_id") or raw.get("id"),
        status=raw.get("status") or ("done" if urls else "pending"),
        urls=urls,
        raw=raw,
    )


def _parse_video(raw: Dict[str, Any]) -> VideoResult:
    urls: List[str] = []
    if isinstance(raw.get("urls"), list):
        urls = [u for u in raw["urls"] if isinstance(u, str)]
    elif isinstance(raw.get("url"), str):
        urls = [raw["url"]]
    return VideoResult(
        job_id=raw.get("job_id") or raw.get("id"),
        status=raw.get("status") or ("done" if urls else "pending"),
        urls=urls,
        raw=raw,
    )


def _parse_voice(raw: Dict[str, Any]) -> VoiceResult:
    url = raw.get("url")
    if not isinstance(url, str):
        url = None
    return VoiceResult(
        job_id=raw.get("job_id") or raw.get("id"),
        status=raw.get("status") or ("done" if url else "pending"),
        url=url,
        raw=raw,
    )
