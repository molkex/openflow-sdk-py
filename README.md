# openflow — Python SDK and CLI

Thin, dependency-light client for [openflowmcp.com](https://openflowmcp.com) — a single API key gives you
LLM chat (Anthropic / OpenAI / Gemini compatible), image, video and voice generation on top of your own
Google-account pool.

## Install

```bash
pip install git+https://github.com/molkex/openflow-sdk-py.git
```

Only runtime dependency is `httpx>=0.27`. Python 3.10+.

## Configure

Get an `fk_...` key from your cabinet, then:

```bash
export OPENFLOW_API_KEY=fk_...
# optional, defaults to https://openflowmcp.com
export OPENFLOW_BASE_URL=https://openflowmcp.com
```

## CLI

```bash
openflow                          # interactive chat REPL
openflow chat "one-shot question"
openflow chat -m claude-sonnet-4-5 --stream "..."
openflow chat --account-tag production "..."
openflow models                   # list live catalog
openflow accounts                 # list connected Google accounts
openflow image "a cat" --out cat.png
openflow video "rain on a window" --model veo_3_1_r2v --duration 4 --out rain.mp4
openflow voice "hello there" --out hello.wav
openflow doctor                   # check auth, quota, account
openflow config
openflow version
```

Interactive REPL commands: `/model <id>`, `/system <prompt>`, `/clear`, `/models`, `/exit`.

## Python

```python
from openflow import OpenFlow

with OpenFlow() as of:
    reply = of.chat(
        model="gemini-3.5-flash-low",
        messages=[{"role": "user", "content": "hi"}],
        system="be concise",
        max_tokens=200,
    )
    print(reply.text, reply.usage.input_tokens, reply.usage.output_tokens)

    for chunk in of.chat_stream(model="m", messages=[{"role": "user", "content": "stream pls"}]):
        print(chunk.text_delta, end="", flush=True)
```

Async:

```python
import asyncio
from openflow import AsyncOpenFlow

async def main():
    async with AsyncOpenFlow() as of:
        reply = await of.chat(model="m", messages=[{"role": "user", "content": "hi"}])
        print(reply.text)

asyncio.run(main())
```

Account routing — pin a request to one Google farm account:

```python
of.chat(..., account_email="farm1@gmail.com")
of.chat(..., account_tag="production")
```

Image / video / voice:

```python
img = of.generate_image("a cat in boots", count=1, aspect="1:1")
print(img.urls)                       # or img.job_id if queued

vid = of.generate_video("rain on glass", model="veo_3_1_r2v", duration=4)
print(vid.job_id)

audio = of.generate_voice("hello", voice_id="...")
```

## Compatibility

openFlow's `/llm` endpoint speaks the Anthropic Messages API (`/v1/messages`), the OpenAI Chat Completions
API (`/v1/chat/completions`) and the Gemini native API. This SDK uses the Anthropic shape under the hood;
the server translates to whichever upstream the model lives on.

If you prefer the official `anthropic` or `openai` SDKs, point them at `https://openflowmcp.com/llm`
(Anthropic) or `https://openflowmcp.com/llm/v1` (OpenAI). See the integrations page at
<https://openflowmcp.com/docs/clients>.

## Errors

```python
from openflow import AuthError, QuotaError, UpstreamError, OpenFlowError

try:
    of.chat(...)
except AuthError:      # 401/403
    ...
except QuotaError:     # 429
    ...
except UpstreamError:  # 5xx
    ...
except OpenFlowError:  # everything else
    ...
```

## Branded CLI wrappers

Installing this package also installs thin wrappers around popular coding CLIs
that route through openFlow — zero mention of the upstream provider:

```bash
export OPENFLOW_API_KEY=fk_...

openflow-code "fix the bug in main.py"   # Claude Code CLI via openFlow
openflow-aider path/to/file              # aider via openFlow
openflow-codex "..."                     # OpenAI Codex CLI via openFlow
openflow-cursor                          # writes ~/.cursor/mcp.json
```

Each wrapper reads `OPENFLOW_API_KEY`, maps it to the standard provider env
var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …), points the base URL at
`https://openflowmcp.com/llm`, and `exec()`s the real CLI.

If you already have the upstream SDK installed and want to skip ours:

```bash
export ANTHROPIC_API_KEY="fk_your_openflow_key"
export ANTHROPIC_BASE_URL="https://openflowmcp.com/llm"
claude "..."
```

## License

MIT.
