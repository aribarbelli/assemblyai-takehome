"""Stream every recorded clip through AssemblyAI's real-time STT and check the learner-specific
failure modes from docs/evaluation-plan.md. Results go to the terminal and evals/results.md.

    python evals/run.py

Each clip is streamed in 50 ms chunks at real-time pace, exactly as the tutor's mic audio is, under
several configurations. The same audio every run makes configurations comparable, which talking to
the live demo can't do.
"""

import asyncio
import json
import os
import re
import sys
import unicodedata
import wave
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from language_tts import NATIVE_VOICES  # noqa: E402  (the tutor's languages)

from clips import CLIPS  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

URL = "wss://streaming.assemblyai.com/v3/ws"
CLIP_DIR = Path(__file__).parent / "clips"
CHUNK = 1600  # 50 ms of 16 kHz 16-bit mono, the size the tutor streams
MAX_CONCURRENT = 1  # parallel sessions came back empty in testing; one at a time is reliable

# The tutor's settings, as in agent.py.
TUTOR = {
    "speech_model": "assemblyai-stt-3-7-realtime-agent",
    "language_codes": ["en", *NATIVE_VOICES],
    "mode": "balanced",
    "min_turn_silence": 600,
    "max_turn_silence": 2000,
    "vad_threshold": 0.2,
}

CONFIGS = {
    "tutor": lambda clip: TUTOR,
    # What the tutor could do next: pass the words it just taught as key terms.
    "tutor + taught words": lambda clip: (
        {**TUTOR, "keyterms_prompt": clip["taught"]} if clip.get("taught") else None
    ),
    # The balanced preset's own turn timing (128 ms / 1280 ms), which the tutor overrides.
    "preset turn timing": lambda clip: {
        k: v for k, v in TUTOR.items() if k not in ("min_turn_silence", "max_turn_silence")
    },
    # Contextual prompt describing a learner who mispronounces (prompt is context, not instructions,
    # per AssemblyAI's docs). Tested as a fix for the model correcting wrong attempts.
    "tutor + learner context": lambda clip: {
        **TUTOR,
        "prompt": "Language lesson. A native English speaker is practicing Spanish and "
        "Portuguese phrases out loud and often mispronounces words.",
    },
    # No language steering: all 32 languages, as in the extra-credit interpreter.
    "all 32 languages": lambda clip: {k: v for k, v in TUTOR.items() if k != "language_codes"},
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def contains(transcript: str, phrase: str) -> bool:
    t, p = normalize(transcript), normalize(phrase)
    if re.search(r"[一-鿿]", p):  # Chinese has no spaces between words
        return p.replace(" ", "") in t.replace(" ", "")
    return re.search(rf"(^| ){re.escape(p)}( |$)", t) is not None


class TooManySessions(Exception):
    pass


async def transcribe(http: aiohttp.ClientSession, pcm: bytes, settings: dict) -> list[str]:
    # The account allows only a few concurrent sessions, and a closed session takes a moment to
    # be released, so wait and retry instead of failing.
    for attempt in range(8):
        try:
            return await _transcribe_once(http, pcm, settings)
        except TooManySessions:
            await asyncio.sleep(5 + 5 * attempt)
    raise RuntimeError("still too many concurrent sessions after retrying")


async def _transcribe_once(http: aiohttp.ClientSession, pcm: bytes, settings: dict) -> list[str]:
    params = {"sample_rate": 16000, "encoding": "pcm_s16le"}
    for key, value in settings.items():
        params[key] = json.dumps(value) if isinstance(value, list) else value
    turns: list[str] = []
    async with http.ws_connect(
        f"{URL}?{urlencode(params)}", headers={"Authorization": os.environ["ASSEMBLYAI_API_KEY"]}
    ) as ws:

        async def send() -> None:
            silence = b"\0" * CHUNK
            for i in range(0, len(pcm), CHUNK):
                await ws.send_bytes(pcm[i : i + CHUNK])
                await asyncio.sleep(0.05)
            for _ in range(50):  # 2.5 s of silence so the last turn can end on its own
                await ws.send_bytes(silence)
                await asyncio.sleep(0.05)
            await ws.send_str(json.dumps({"type": "Terminate"}))

        sender = asyncio.create_task(send())
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError(f"session closed early: {msg.type} {msg.data} {ws.close_code}")
            data = json.loads(msg.data)
            if data["type"] == "Turn" and data.get("end_of_turn") and data.get("turn_is_formatted"):
                if data["transcript"].strip():
                    turns.append(data["transcript"])
            elif data["type"] == "Termination":
                break
            elif data["type"] == "Error" and "concurrent" in data.get("error", ""):
                sender.cancel()
                raise TooManySessions()
            elif data["type"] not in ("Turn", "Begin", "SpeechStarted"):
                raise RuntimeError(f"unexpected message: {data}")
        else:
            raise RuntimeError(f"session closed before Termination (code {ws.close_code})")
        sender.cancel()
    return turns


def score(clip: dict, turns: list[str]) -> tuple[bool, str]:
    transcript = " ".join(turns)
    problems = []
    for phrase in [clip["target"], *clip.get("also", [])]:
        if not contains(transcript, phrase):
            problems.append(f"missing '{phrase}'")
    if clip.get("must_not") and contains(transcript, clip["must_not"]):
        problems.append(f"auto-corrected to '{clip['must_not']}'")
    if clip.get("single_turn") and len(turns) > 1:
        problems.append(f"split into {len(turns)} turns")
    return (not problems, "; ".join(problems))


async def main() -> None:
    clips = [c for c in CLIPS if (CLIP_DIR / f"{c['name']}.wav").exists()]
    missing = [c["name"] for c in CLIPS if c not in clips]
    if missing:
        print(f"Not recorded yet (skipped): {', '.join(missing)}")
    if not clips:
        sys.exit("No clips found. Record them first: python evals/record.py")

    jobs = []
    for clip in clips:
        with wave.open(str(CLIP_DIR / f"{clip['name']}.wav")) as f:
            pcm = f.readframes(f.getnframes())
        for config_name, make in CONFIGS.items():
            if (settings := make(clip)) is not None:
                jobs.append((clip, config_name, pcm, settings))

    print(f"Streaming {len(clips)} clips x {len(CONFIGS)} configurations in real time "
          f"({len(jobs)} sessions, a few minutes)...")
    limit = asyncio.Semaphore(MAX_CONCURRENT)
    async with aiohttp.ClientSession() as http:

        async def run(job):
            clip, config_name, pcm, settings = job
            async with limit:
                turns = await transcribe(http, pcm, settings)
            ok, why = score(clip, turns)
            print(f"  {'PASS' if ok else 'FAIL'}  {clip['name']:<24} {config_name:<22} {' | '.join(turns)}")
            return clip["name"], config_name, turns, ok, why

        results = await asyncio.gather(*(run(job) for job in jobs))

    by_clip = {(name, config): (turns, ok, why) for name, config, turns, ok, why in results}
    lines = [
        "# STT evaluation results",
        "",
        f"Run {datetime.now():%Y-%m-%d %H:%M}. {len(clips)} clips recorded by one speaker, streamed "
        "in real time through `assemblyai-stt-3-7-realtime-agent`. See `evals/clips.py` for the "
        "checks and `docs/evaluation-plan.md` for why each one matters.",
        "",
        "| Clip | What it tests | " + " | ".join(CONFIGS) + " |",
        "|---|---|" + "---|" * len(CONFIGS),
    ]
    for clip in clips:
        cells = []
        for config in CONFIGS:
            if (clip["name"], config) not in by_clip:
                cells.append("–")
                continue
            turns, ok, why = by_clip[(clip["name"], config)]
            cells.append("✅" if ok else f"❌ {why}")
        lines.append(f"| `{clip['name']}` | {clip['bucket']} | " + " | ".join(cells) + " |")
    totals = [
        sum(1 for (n, c), (_, ok, _) in by_clip.items() if c == config and ok)
        for config in CONFIGS
    ]
    counts = [sum(1 for (n, c) in by_clip if c == config) for config in CONFIGS]
    lines.append("| **Passed** | | " + " | ".join(f"**{t}/{n}**" for t, n in zip(totals, counts)) + " |")
    lines += ["", "## Transcripts", ""]
    for clip in clips:
        lines.append(f"**`{clip['name']}`**, said: {clip['say']}")
        lines.append("")
        for config in CONFIGS:
            if (clip["name"], config) in by_clip:
                turns = by_clip[(clip["name"], config)][0]
                shown = " ⏎ ".join(f"“{t}”" for t in turns) or "(nothing)"
                lines.append(f"- {config}: {shown}")
        lines.append("")
    out = Path(__file__).parent / "results.md"
    out.write_text("\n".join(lines))
    print(f"\nPassed: " + ", ".join(f"{c} {t}/{n}" for c, t, n in zip(CONFIGS, totals, counts)))
    print(f"Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
