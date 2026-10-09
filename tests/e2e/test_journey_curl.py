"""Wire-level sanity: raw httpx requests hit the same routes/headers the SDK uses.

Proves the SDK adds no hidden middleware: SDK request == hand-built request
(modulo the user-agent header).
"""
import json

import httpx
import respx

from openflow import OpenFlow

from .conftest import ACCTS, API_KEY, IMAGE, LLM, MODELS, VIDEO, VOICE

LLM_HEADERS = {"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
FLOW_HEADERS = {"Authorization": f"Bearer {API_KEY}", "content-type": "application/json"}


def _wire(req: httpx.Request):
    """Comparable view of a request, ignoring user-agent and transport headers."""
    skip = {"user-agent", "host", "accept", "accept-encoding", "connection", "content-length"}
    headers = {k.lower(): v for k, v in req.headers.items() if k.lower() not in skip}
    return req.method, str(req.url), headers, req.content


@respx.mock
def test_raw_messages(anthropic_reply):
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1024}
    r = httpx.post(LLM, headers=LLM_HEADERS, json=body)
    assert r.status_code == 200 and r.json()["content"][0]["text"] == "hello world"
    with OpenFlow(api_key=API_KEY) as of:
        of.chat(model="m", messages=body["messages"])
    raw, sdk = route.calls[0].request, route.calls[1].request
    assert _wire(raw) == _wire(sdk)


@respx.mock
def test_raw_models():
    route = respx.get(MODELS).mock(return_value=httpx.Response(200, json={"data": [{"id": "a"}]}))
    r = httpx.get(MODELS, headers=LLM_HEADERS)
    assert r.json()["data"][0]["id"] == "a"
    with OpenFlow(api_key=API_KEY) as of:
        of.list_models()
    assert _wire(route.calls[0].request)[:3] == _wire(route.calls[1].request)[:3]


@respx.mock
def test_raw_image():
    route = respx.post(IMAGE).mock(return_value=httpx.Response(200, json={"id": "j", "urls": ["u"]}))
    body = {"prompt": "fox", "count": 1, "aspect": "16:9"}
    assert httpx.post(IMAGE, headers=FLOW_HEADERS, json=body).json()["id"] == "j"
    with OpenFlow(api_key=API_KEY) as of:
        of.generate_image("fox")
    assert _wire(route.calls[0].request) == _wire(route.calls[1].request)


@respx.mock
def test_raw_video():
    route = respx.post(VIDEO).mock(return_value=httpx.Response(200, json={"id": "v"}))
    body = {"prompt": "waves", "model": "veo_3_1_r2v", "duration": 4}
    httpx.post(VIDEO, headers=FLOW_HEADERS, json=body)
    with OpenFlow(api_key=API_KEY) as of:
        of.generate_video("waves")
    assert _wire(route.calls[0].request) == _wire(route.calls[1].request)


@respx.mock
def test_raw_voice():
    route = respx.post(VOICE).mock(return_value=httpx.Response(200, json={"id": "s", "url": "u"}))
    httpx.post(VOICE, headers=FLOW_HEADERS, json={"text": "hello"})
    with OpenFlow(api_key=API_KEY) as of:
        of.generate_voice("hello")
    assert _wire(route.calls[0].request) == _wire(route.calls[1].request)


@respx.mock
def test_raw_accounts():
    route = respx.get(ACCTS).mock(return_value=httpx.Response(
        200, json={"accounts": [{"id": 1, "email": "a@b.c", "tag": "t"}]}))
    assert httpx.get(ACCTS, headers=FLOW_HEADERS).json()["accounts"][0]["email"] == "a@b.c"
    with OpenFlow(api_key=API_KEY) as of:
        accts = of.list_accounts()
    assert accts[0].email == "a@b.c" and accts[0].tag == "t"
    assert _wire(route.calls[0].request)[:3] == _wire(route.calls[1].request)[:3]


@respx.mock
def test_sdk_user_agent_is_identifiable(anthropic_reply):
    route = respx.post(LLM).mock(return_value=httpx.Response(200, json=anthropic_reply))
    with OpenFlow(api_key=API_KEY) as of:
        of.chat(model="m", messages=[{"role": "user", "content": "hi"}])
    assert route.calls.last.request.headers["user-agent"].startswith("openflow-sdk-py/")
    assert json.loads(route.calls.last.request.content)["model"] == "m"
