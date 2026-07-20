"""doubao-ask — HTTP/MCP wrapper around `opencli doubao ask-cited`.

Exposes Doubao Q&A (answer text + citation links) as a JSON API and as an
MCP (streamable HTTP) tool. All asks are serialized AND rate-limited: the
underlying browser session is single-threaded, and hammering Doubao triggers
its anti-bot defenses.
"""
import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import time

from fastapi import FastAPI, HTTPException, Response
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

OPENCLI = shutil.which("opencli") or "opencli"
SUBPROCESS_MARGIN_S = 90  # slack beyond the doubao wait timeout for CLI/browser overhead
LOCK_WAIT_S = 300  # how long a request may queue behind another before 429
RATE_MIN_INTERVAL_S = float(os.environ.get("RATE_MIN_INTERVAL_S", "30"))

_lock = asyncio.Lock()
_last_ask_started = 0.0


# --- MCP surface (mounted below) -------------------------------------------
# Mounted at "/" with streamable_http_path="/mcp" so the endpoint answers at
# exactly /mcp (a sub-path mount would 307-redirect /mcp → /mcp/ and some
# MCP clients drop POST bodies on redirects).
# DNS-rebinding protection is off: the service is reachable only on the
# tailnet, and its Host header is the node's tailnet IP (rejected by default).
mcp = FastMCP(
    "doubao-ask",
    streamable_http_path="/mcp",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
mcp_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="doubao-ask", version="0.2.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    timeout: int = Field(default=120, ge=10, le=600)


class Citation(BaseModel):
    name: str
    url: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    elapsed_ms: int


async def run_opencli(*args: str, timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        OPENCLI, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"opencli timed out after {timeout:.0f}s")
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def ask_locked(question: str, timeout: int) -> dict:
    """Serialized + rate-limited ask. Returns {answer, citations, elapsed_ms}."""
    global _last_ask_started
    started = time.monotonic()
    try:
        await asyncio.wait_for(_lock.acquire(), timeout=LOCK_WAIT_S)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="service busy, retry later",
            headers={"Retry-After": "60"},
        )
    try:
        # Anti-bot throttle: never start two asks closer than RATE_MIN_INTERVAL_S.
        wait = RATE_MIN_INTERVAL_S - (time.monotonic() - _last_ask_started)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_ask_started = time.monotonic()
        rc, out, err = await run_opencli(
            "doubao", "ask-cited", question,
            "--timeout", str(timeout), "-f", "json",
            timeout=timeout + SUBPROCESS_MARGIN_S,
        )
    finally:
        _lock.release()

    if rc != 0:
        raise HTTPException(
            status_code=502,
            detail={"msg": "opencli failed", "exit": rc, "stderr": err[-500:]},
        )
    try:
        row = json.loads(out)[0]
        answer = row.get("Answer") or ""
        citations = json.loads(row.get("Citations") or "[]")
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"msg": f"unparseable opencli output: {exc}", "raw": out[-500:]},
        )
    if isinstance(citations, dict) and "error" in citations:  # adapter-level timeout signal
        raise HTTPException(status_code=504, detail=citations["error"])
    if not answer:
        raise HTTPException(status_code=504, detail="empty answer from doubao")
    return {
        "answer": answer,
        "citations": citations,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


@mcp.tool()
async def doubao_ask(question: str, timeout: int = 120) -> dict:
    """向豆包提问，返回回答全文与引用链接（联网搜索时）。
    Ask Doubao (doubao.com) a question; returns the full answer text plus
    citation links when the answer used web search."""
    return await ask_locked(question, timeout)


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    return AskResponse(**(await ask_locked(req.question, req.timeout)))


@app.get("/health")
async def health():
    # Kept cheap on purpose: vinyard probes this every 2s during the deploy gate.
    return {"status": "ok"}


class EvalRequest(BaseModel):
    js: str = Field(min_length=1, max_length=20000)


@app.get("/setup/screenshot")
async def setup_screenshot():
    """PNG screenshot of the container browser — used for QR-code login setup."""
    async with _lock:
        rc, out, err = await run_opencli("browser", "setup", "screenshot", timeout=60)
    if rc != 0:
        raise HTTPException(status_code=502, detail={"msg": "screenshot failed", "stderr": err[-300:]})
    try:
        png = base64.b64decode(out.strip())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"bad screenshot payload: {exc}")
    return Response(content=png, media_type="image/png")


@app.post("/setup/eval")
async def setup_eval(req: EvalRequest):
    """Run JS in the container browser page — setup/escape-hatch endpoint (tailnet only)."""
    async with _lock:
        rc, out, err = await run_opencli("browser", "setup", "eval", req.js, timeout=60)
    return {"exit": rc, "output": out[-2000:], "stderr": err[-300:] if rc != 0 else ""}


class CliRequest(BaseModel):
    args: list[str] = Field(min_length=1, max_length=8)


# Whitelisted opencli invocations for container-side setup/maintenance
# (e.g. trigger a captcha with `doubao send`, then `doubao solve-slider`).
SETUP_CLI_ALLOW = {
    ("doubao", "new"), ("doubao", "send"), ("doubao", "read"),
    ("doubao", "status"), ("doubao", "whoami"), ("doubao", "solve-slider"),
    ("browser", "setup", "open"), ("browser", "setup", "click"),
    ("browser", "setup", "type"), ("browser", "setup", "scroll"),
    ("browser", "setup", "wait"), ("browser", "setup", "state"),
    ("browser", "setup", "screenshot"),
}


@app.post("/setup/cli")
async def setup_cli(req: CliRequest):
    """Run a whitelisted opencli command in the container (operator hatch)."""
    allowed = any(tuple(req.args[: len(head)]) == head for head in SETUP_CLI_ALLOW)
    if not allowed:
        raise HTTPException(status_code=400, detail=f"command not whitelisted: {req.args[:3]}")
    async with _lock:
        rc, out, err = await run_opencli(*req.args, timeout=150)
    return {"exit": rc, "stdout": out[-3000:], "stderr": err[-500:]}


@app.get("/status")
async def status():
    """Deeper diagnostic: is the opencli browser bridge up and doubao logged in?"""
    async with _lock:
        rc, out, err = await run_opencli("doubao", "whoami", timeout=90)
    logged_in = bool(re.search(r"logged_in:\s*true", out))
    user = re.search(r"^name:\s*(.+)$", out, re.M)
    return {
        "opencli_exit": rc,
        "logged_in": logged_in,
        "user": user.group(1).strip().strip("'\"") if user else None,
        "stderr": err[-300:] if rc != 0 else "",
    }


# MCP streamable-HTTP endpoint at /mcp (mounted last so the explicit routes
# above always win).
app.mount("/", mcp_app)
