"""Serves the web UI and mints LiveKit room tokens for the browser. Run with `python server.py`."""

import os
import uuid
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

load_dotenv()

WEB_DIR = Path(__file__).parent / "web"
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


app = web.Application()
app.router.add_get("/token", token)
app.router.add_get("/", lambda _: web.FileResponse(WEB_DIR / "index.html"))
app.router.add_get("/logo.svg", lambda _: web.FileResponse(LOGO))

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Open http://localhost:{port}")
    web.run_app(app, port=port, print=None)
