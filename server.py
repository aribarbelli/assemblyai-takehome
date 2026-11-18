"""Serves the web UI and mints LiveKit room tokens for the browser. Run with `python server.py`."""

import asyncio
import json
import os
import uuid
from urllib.parse import urlencode
from pathlib import Path

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from livekit import api

load_dotenv()

WEB_DIR = Path(__file__).parent / "web"
EVALS_DIR = Path(__file__).parent / "evals"
LOGO = Path(__file__).parent / "assemblyai-logo.svg"


async def token(_: web.Request) -> web.Response:
    # A fresh room per conversation; the agent server auto-joins every new room.
    room = f"tutor-{uuid.uuid4().hex[:8]}"
    identity = f"learner-{uuid.uuid4().hex[:6]}"
    jwt = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return web.json_response({"url": os.environ["LIVEKIT_URL"], "token": jwt, "room": room})


# The Extra Credit interpreter talks to AssemblyAI straight from the browser (Streaming STT over a
# WebSocket, TTS over HTTP). The browser must never see the API key, so it asks for a short-lived
# temporary token per connection instead.
TOKEN_URL = "https://token.us.assemblyai.com/v1/token"
TOKEN_PRODUCTS = {"tts"}  # Streaming STT goes through /interpreter/ws instead (see below)


async def assemblyai_token(request: web.Request) -> web.Response:
    product = request.query.get("product", "")
    if product not in TOKEN_PRODUCTS:
        raise web.HTTPBadRequest(text="product must be tts")
    body = {
        "product": product,
        "expires_in_seconds": 60,  # window to open the connection, not the session length
        "max_session_duration_seconds": 900,
        # A token can open any product the account can unless narrowed: this one opens only its own.
        "access": {p: {"enabled": p == product} for p in ("streaming", "tts", "speech_to_speech")},
    }
    async with aiohttp.ClientSession() as http:
        async with http.post(
            TOKEN_URL, json=body, headers={"Authorization": os.environ["ASSEMBLYAI_API_KEY"]}
        ) as resp:
            if resp.status != 200:
                raise web.HTTPBadGateway(text=f"token request failed: {resp.status} {await resp.text()}")
            return web.json_response({"token": (await resp.json())["token"]})


# The interpreter's translation prompt. It normally runs inside the Streaming STT session
# (the `llm_gateway` connection parameter), where AssemblyAI fills in {{turn}} with each final
# transcript. If a translation doesn't come back (the docs say a failed or timed-out gateway call
# sends nothing), the page falls back to /interpreter/translate, which runs the same prompt here.
INTERPRETER_MODEL = "gemma-4-31b"
INTERPRETER_PROMPT = """You are a live interpreter. The speaker may mix several languages in one utterance.

Utterance: {{turn}}

Reply with JSON only, no code fences, in this shape:
{"english": "natural English translation of the whole utterance", "segments": [{"lang": "ISO 639-1 code", "text": "the original words in that language, verbatim"}]}
The segments must cover the utterance in order."""
LLM_GATEWAY_URL = "https://llm-gateway.assemblyai.com/v1/chat/completions"


async def interpreter_translate(request: web.Request) -> web.Response:
    text = str((await request.json()).get("text", ""))[:2000]
    if not text.strip():
        raise web.HTTPBadRequest(text="text is required")
    body = {
        "model": INTERPRETER_MODEL,
        "messages": [{"role": "user", "content": INTERPRETER_PROMPT.replace("{{turn}}", text)}],
        "max_tokens": 600,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(
            LLM_GATEWAY_URL, json=body, headers={"Authorization": os.environ["ASSEMBLYAI_API_KEY"]}
        ) as resp:
            if resp.status != 200:
                raise web.HTTPBadGateway(text=f"LLM Gateway {resp.status}: {await resp.text()}")
            data = await resp.json()
    return web.json_response({"content": data["choices"][0]["message"]["content"]})


STREAMING_URL = "wss://streaming.assemblyai.com/v3/ws"
# Connection parameters the page may set; the translation config is added here, server-side.
STREAMING_PARAMS = {"speech_model", "sample_rate", "encoding", "language_detection", "language_codes",
                    "min_turn_silence", "max_turn_silence"}


async def interpreter_ws(request: web.Request) -> web.WebSocketResponse:
    """Relay the page's Streaming STT session to AssemblyAI, authenticated with the API key.

    Why not let the browser connect directly with a temporary token? Tested: a token-authenticated
    session returns at most 10 built-in translations (LLMGatewayResponse), then silently stops,
    even with a higher LLM Gateway limit on the token. The same session on the API key translated
    all 16 turns. Relaying keeps the key on the server and the translation inside the STT stream.
    """
    params = {k: v for k, v in request.query.items() if k in STREAMING_PARAMS}
    params["llm_gateway"] = json.dumps(
        {"model": INTERPRETER_MODEL, "prompt": INTERPRETER_PROMPT, "max_tokens": 600}
    )
    browser = web.WebSocketResponse()
    await browser.prepare(request)
    async with aiohttp.ClientSession() as http:
        try:
            upstream = await http.ws_connect(
                f"{STREAMING_URL}?{urlencode(params)}",
                headers={"Authorization": os.environ["ASSEMBLYAI_API_KEY"]},
            )
        except aiohttp.ClientError as e:
            await browser.close(code=1011, message=f"upstream connect failed: {e}".encode()[:120])
            return browser

        async def to_upstream() -> None:
            async for msg in browser:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await upstream.send_bytes(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    await upstream.send_str(msg.data)
            await upstream.close()

        async def to_browser() -> None:
            async for msg in upstream:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await browser.send_str(msg.data)
            await browser.close(code=upstream.close_code or 1000)

        tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Let the other direction finish briefly (Terminate -> Termination flush), then stop.
        await asyncio.wait(tasks, timeout=5)
        for t in tasks:
            t.cancel()
        await upstream.close()
    return browser


async def eval_results(_: web.Request) -> web.Response:
    """The latest evals/run.py results, plus which clips have a local recording to play."""
    path = EVALS_DIR / "results.json"
    if not path.exists():
        raise web.HTTPNotFound(text="No results yet: run python evals/run.py")
    data = json.loads(path.read_text())
    for clip in data["clips"]:
        clip["has_audio"] = (EVALS_DIR / "clips" / f"{clip['name']}.wav").exists()
    return web.json_response(data)


async def eval_clip(request: web.Request) -> web.FileResponse:
    # Recordings are local only (gitignored). Names are restricted to the clip-name pattern.
    name = request.match_info["name"]
    path = EVALS_DIR / "clips" / f"{name}.wav"
    if not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


app = web.Application()
app.router.add_get("/token", token)
app.router.add_get("/assemblyai-token", assemblyai_token)
app.router.add_post("/interpreter/translate", interpreter_translate)
app.router.add_get("/interpreter/ws", interpreter_ws)
app.router.add_get("/evals/results", eval_results)
app.router.add_get(r"/evals/clips/{name:[a-z0-9_]+}.wav", eval_clip)
app.router.add_get("/", lambda _: web.FileResponse(WEB_DIR / "index.html"))
app.router.add_get("/logo.svg", lambda _: web.FileResponse(LOGO))

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Open http://localhost:{port}")
    web.run_app(app, port=port, print=None)
