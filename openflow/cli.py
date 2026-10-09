"""openflow CLI — argparse-only, no extra deps (rich optional for pretty output)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._version import __version__
from .client import DEFAULT_BASE_URL, OpenFlow
from .errors import OpenFlowError

DEFAULT_MODEL = "gemini-3.5-flash-low"


def _try_rich_print(text: str) -> None:
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        Console().print(Markdown(text))
    except Exception:
        print(text)


def _client(args: argparse.Namespace) -> OpenFlow:
    return OpenFlow(api_key=getattr(args, "api_key", None), base_url=getattr(args, "base_url", None))


def _mask(key: Optional[str]) -> str:
    if not key:
        return "(unset)"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


# ─────────── commands ───────────


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"openflow {__version__}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    key = args.api_key or os.environ.get("OPENFLOW_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    base = args.base_url or os.environ.get("OPENFLOW_BASE_URL") or DEFAULT_BASE_URL
    print(f"OPENFLOW_API_KEY = {_mask(key)}")
    print(f"OPENFLOW_BASE_URL = {base}")
    print(f"SDK version      = {__version__}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    with _client(args) as of:
        models = of.list_models()
    if args.refresh:
        # Nothing to cache yet; the catalog is live.
        pass
    if not models:
        print("(empty catalog)")
        return 0
    w = max(len(m.id) for m in models)
    for m in models:
        label = m.label or ""
        prov = m.provider or ""
        print(f"{m.id.ljust(w)}  {prov:12}  {label}")
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    with _client(args) as of:
        accs = of.list_accounts()
    if not accs:
        print("(no connected Google accounts)")
        return 0
    w = max(len(a.email) for a in accs)
    for a in accs:
        tag = f"#{a.tag}" if a.tag else ""
        status = "active" if a.active else "disabled"
        print(f"{a.email.ljust(w)}  {status:9}  {tag}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    model = args.model or DEFAULT_MODEL
    prompt = " ".join(args.prompt).strip() if args.prompt else ""
    if not prompt:
        print("usage: openflow chat [-m MODEL] 'your question'", file=sys.stderr)
        return 2
    messages = [{"role": "user", "content": prompt}]
    with _client(args) as of:
        if args.stream:
            try:
                for chunk in of.chat_stream(
                    model=model,
                    messages=messages,
                    system=args.system,
                    max_tokens=args.max_tokens,
                    account_email=args.account_email,
                    account_tag=args.account_tag,
                ):
                    if chunk.text_delta:
                        print(chunk.text_delta, end="", flush=True)
                print()
                return 0
            except OpenFlowError as e:
                print(f"\nerror: {e}", file=sys.stderr)
                return 1
        try:
            reply = of.chat(
                model=model,
                messages=messages,
                system=args.system,
                max_tokens=args.max_tokens,
                account_email=args.account_email,
                account_tag=args.account_tag,
            )
        except OpenFlowError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(reply.raw, ensure_ascii=False, indent=2))
    elif args.markdown:
        _try_rich_print(reply.text)
    else:
        print(reply.text)
    return 0


def cmd_image(args: argparse.Namespace) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("usage: openflow image 'prompt'", file=sys.stderr)
        return 2
    with _client(args) as of:
        try:
            res = of.generate_image(
                prompt,
                count=args.count,
                aspect=args.aspect,
                account_email=args.account_email,
                account_tag=args.account_tag,
            )
        except OpenFlowError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if res.status != "done" and res.job_id and not res.urls:
            print(f"job queued: {res.job_id} — poll with: openflow job {res.job_id}")
            return 0
        _print_and_download(res.urls, args.out, "image")
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("usage: openflow video 'prompt' --model veo_3_1_r2v", file=sys.stderr)
        return 2
    with _client(args) as of:
        try:
            res = of.generate_video(
                prompt,
                model=args.model,
                duration=args.duration,
                account_email=args.account_email,
                account_tag=args.account_tag,
            )
        except OpenFlowError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if res.status != "done" and res.job_id and not res.urls:
            print(f"job queued: {res.job_id} — poll with: openflow job {res.job_id}")
            return 0
        _print_and_download(res.urls, args.out, "video")
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("usage: openflow voice 'text to speak' --out file.wav", file=sys.stderr)
        return 2
    with _client(args) as of:
        try:
            res = of.generate_voice(
                text,
                voice_id=args.voice_id,
                account_email=args.account_email,
                account_tag=args.account_tag,
            )
        except OpenFlowError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not res.url:
            print(f"job queued: {res.job_id} — poll with: openflow job {res.job_id}")
            return 0
        _print_and_download([res.url], args.out, "voice")
    return 0


def cmd_job(args: argparse.Namespace) -> int:
    with _client(args) as of:
        data = of.check_job(args.job_id)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    key = args.api_key or os.environ.get("OPENFLOW_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    base = args.base_url or os.environ.get("OPENFLOW_BASE_URL") or DEFAULT_BASE_URL
    ok = True

    def _check(label: str, cond: bool, hint: str = "") -> None:
        nonlocal ok
        status = "OK" if cond else "FAIL"
        line = f"[{status}] {label}"
        if hint and not cond:
            line += f" — {hint}"
        print(line)
        if not cond:
            ok = False

    _check("API key present", bool(key), "export OPENFLOW_API_KEY=fk_...")
    _check("Base URL", base.startswith("http"), "set OPENFLOW_BASE_URL")

    if key:
        try:
            with _client(args) as of:
                status = of.status()
            _check("auth (/me/llm-status)", True)
            plan = status.get("plan") or status.get("tier") or "unknown"
            print(f"       plan: {plan}")
            quota = status.get("quota") or status.get("quotas")
            if quota:
                print(f"       quota: {json.dumps(quota, ensure_ascii=False)}")
            google_ok = bool(status.get("google_connected") or status.get("accounts"))
            _check(
                "Google account connected",
                google_ok,
                f"open {base}/connect-google to link one",
            )
        except Exception as e:
            _check("auth (/me/llm-status)", False, f"{e}")
    try:
        with _client(args) as of:
            models = of.list_models()
        _check(f"catalog reachable ({len(models)} models)", True)
    except Exception as e:
        _check("catalog reachable", False, str(e))
    return 0 if ok else 1


# ───────── REPL ─────────


def cmd_repl(args: argparse.Namespace) -> int:
    model = args.model or DEFAULT_MODEL
    system = args.system
    history: List[Dict[str, Any]] = []
    print(f"openflow {__version__} — interactive chat. /help for commands, /exit to quit.")
    try:
        of = _client(args)
    except OpenFlowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    with of:
        while True:
            try:
                line = input(f"openflow ({model}) > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line.startswith("/"):
                parts = line.split(maxsplit=1)
                cmd = parts[0].lower()
                rest = parts[1] if len(parts) > 1 else ""
                if cmd in ("/exit", "/quit", "/q"):
                    return 0
                if cmd == "/help":
                    print("/model <id>   switch model")
                    print("/system <s>   set system prompt")
                    print("/clear        reset history")
                    print("/models       list available models")
                    print("/exit         quit")
                    continue
                if cmd == "/model":
                    if rest:
                        model = rest.strip()
                        print(f"model: {model}")
                    else:
                        print(f"current: {model}")
                    continue
                if cmd == "/system":
                    system = rest.strip() or None
                    print(f"system: {system or '(none)'}")
                    continue
                if cmd == "/clear":
                    history = []
                    print("(history cleared)")
                    continue
                if cmd == "/models":
                    try:
                        for m in of.list_models():
                            print(f"  {m.id}")
                    except OpenFlowError as e:
                        print(f"error: {e}")
                    continue
                print(f"unknown command: {cmd} (try /help)")
                continue
            history.append({"role": "user", "content": line})
            try:
                reply = of.chat(
                    model=model,
                    messages=history,
                    system=system,
                    max_tokens=args.max_tokens,
                )
            except OpenFlowError as e:
                print(f"error: {e}")
                history.pop()
                continue
            print(reply.text)
            history.append({"role": "assistant", "content": reply.text})


# ───────── helpers ─────────


def _print_and_download(urls: List[str], out: Optional[str], label: str) -> None:
    for i, url in enumerate(urls):
        print(url)
        if out:
            path = Path(out)
            if len(urls) > 1:
                path = path.with_name(f"{path.stem}_{i}{path.suffix}")
            try:
                urllib.request.urlretrieve(url, path)  # noqa: S310 — user asked for save
                print(f"saved: {path}")
            except Exception as e:
                print(f"download failed: {e}", file=sys.stderr)


# ───────── parser ─────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="openflow",
        description="openflow — unified client for openflowmcp.com (LLM chat, image, video, voice).",
    )
    p.add_argument("--api-key", help="override OPENFLOW_API_KEY")
    p.add_argument("--base-url", help="override OPENFLOW_BASE_URL (default https://openflowmcp.com)")
    p.add_argument("-V", "--version", action="store_true", help="print version and exit")

    sub = p.add_subparsers(dest="command")

    pc = sub.add_parser("chat", help="one-shot chat")
    pc.add_argument("prompt", nargs="*")
    pc.add_argument("-m", "--model", default=None)
    pc.add_argument("--system", default=None, help="system prompt")
    pc.add_argument("--max-tokens", type=int, default=1024)
    pc.add_argument("--stream", action="store_true")
    pc.add_argument("--account-email", default=None)
    pc.add_argument("--account-tag", default=None)
    pc.add_argument("--json", action="store_true", help="print raw provider JSON")
    pc.add_argument("--markdown", action="store_true", help="render reply as markdown (needs rich)")
    pc.set_defaults(func=cmd_chat)

    pm = sub.add_parser("models", help="list available models")
    pm.add_argument("--refresh", action="store_true")
    pm.set_defaults(func=cmd_models)

    pa = sub.add_parser("accounts", help="list connected Google accounts")
    pa.set_defaults(func=cmd_accounts)

    pi = sub.add_parser("image", help="generate an image")
    pi.add_argument("prompt", nargs="+")
    pi.add_argument("--count", type=int, default=1)
    pi.add_argument("--aspect", default="16:9")
    pi.add_argument("--out", default=None, help="save first result to file")
    pi.add_argument("--account-email", default=None)
    pi.add_argument("--account-tag", default=None)
    pi.set_defaults(func=cmd_image)

    pv = sub.add_parser("video", help="generate a video")
    pv.add_argument("prompt", nargs="+")
    pv.add_argument("--model", default="veo_3_1_r2v")
    pv.add_argument("--duration", type=int, default=4)
    pv.add_argument("--out", default=None)
    pv.add_argument("--account-email", default=None)
    pv.add_argument("--account-tag", default=None)
    pv.set_defaults(func=cmd_video)

    pvo = sub.add_parser("voice", help="synthesize voice (TTS)")
    pvo.add_argument("text", nargs="+")
    pvo.add_argument("--voice-id", default=None)
    pvo.add_argument("--out", default=None)
    pvo.add_argument("--account-email", default=None)
    pvo.add_argument("--account-tag", default=None)
    pvo.set_defaults(func=cmd_voice)

    pj = sub.add_parser("job", help="check job status by id")
    pj.add_argument("job_id")
    pj.set_defaults(func=cmd_job)

    pd = sub.add_parser("doctor", help="run basic diagnostics")
    pd.set_defaults(func=cmd_doctor)

    pco = sub.add_parser("config", help="print current config")
    pco.set_defaults(func=cmd_config)

    pver = sub.add_parser("version", help="print version")
    pver.set_defaults(func=cmd_version)

    prepl = sub.add_parser("repl", help="interactive chat (default when no args)")
    prepl.add_argument("-m", "--model", default=None)
    prepl.add_argument("--system", default=None)
    prepl.add_argument("--max-tokens", type=int, default=1024)
    prepl.set_defaults(func=cmd_repl)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        return cmd_version(args)
    if not args.command:
        # No subcommand → interactive REPL
        # Ensure attributes expected by cmd_repl exist.
        for attr, default in (("model", None), ("system", None), ("max_tokens", 1024)):
            if not hasattr(args, attr):
                setattr(args, attr, default)
        return cmd_repl(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
