"""doubao-ask — HTTP wrapper around `opencli doubao ask-cited`.

Exposes Doubao Q&A (answer text + citation links) as a small JSON API.
All requests are serialized: the underlying browser session is single-threaded.
"""
import asyncio
import base64
import json
import re
import shutil
import time

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI(title="doubao-ask", version="0.1.0")

OPENCLI = shutil.which("opencli") or "opencli"
SUBPROCESS_MARGIN_S = 90  # slack beyond the doubao wait timeout for CLI/browser overhead
LOCK_WAIT_S = 300  # how long a request may queue behind another before 429

_lock = asyncio.Lock()


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


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    started = time.monotonic()
    try:
        await asyncio.wait_for(_lock.acquire(), timeout=LOCK_WAIT_S)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="service busy, retry later")
    try:
        rc, out, err = await run_opencli(
            "doubao", "ask-cited", req.question,
            "--timeout", str(req.timeout), "-f", "json",
            timeout=req.timeout + SUBPROCESS_MARGIN_S,
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
    return AskResponse(
        answer=answer,
        citations=citations,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


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
