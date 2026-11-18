"""Speak each part of a reply in its own language.

AssemblyAI TTS does not detect language: a session speaks the one language it was opened with.
A tutor reply mixes languages ("In Spanish, that's <es>¿Dónde está la biblioteca?</es> Try it!"),
so the LLM tags foreign phrases and we route each segment to a TTS configured for its language.
Without this, the Spanish phrase is read with an English accent, which defeats the point of a
pronunciation tutor.

Text is streamed segment by segment: English starts speaking as soon as the first tokens arrive,
and a language switch only waits for the closing tag of the foreign phrase.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field

from livekit import rtc
from livekit.agents import APIError
from livekit.plugins import assemblyai

logger = logging.getLogger("tutor.tts")

# The six languages AssemblyAI TTS speaks, each with a native catalog voice.
# (A voice can speak any of the six, but sounds best in the language it was recorded in.)
NATIVE_VOICES = {
    "es": "aai-constanza",  # young woman, Mexican Spanish, even and clear
    "fr": "aai-agathe",  # woman, native French (chosen by ear from the dashboard catalog)
    "de": "aai-magdalena",
    "it": "aai-giada",
    "pt": "aai-iara",  # woman, native Portuguese (chosen by ear from the dashboard catalog)
}
BASE_LANGUAGE = "en"
BASE_VOICE = "aai-kyla"

# One voice for the whole reply (Kyla, told to speak Spanish) sounds like one tutor. Switching to
# a native voice per language gives slightly more authentic pronunciation but sounds like a second
# person cutting in. Set to False to use NATIVE_VOICES instead.
SAME_VOICE_FOR_ALL_LANGUAGES = False  # tried it: Kyla sounds bad in Spanish

# <es>...</es> etc. switch language; <hint>...</hint> is shown on screen but never spoken
# (written respellings like "beeb-lee-oh-TEH-kah" sound terrible read aloud by a TTS voice).
# AssemblyAI closes a TTS session after 120 s with no frame in either direction (the maximum;
# it can't be raised). Every reconnect counts against the account's new-sessions-per-minute limit
# and delays the next phrase, so idle sessions get a KeepAlive well inside that window.
_KEEPALIVE_FRAME = '{"type": "KeepAlive"}'
_KEEPALIVE_INTERVAL_S = 60

_TAG = re.compile(r"<(/?)([a-z]{2}|hint)>")
_MAX_TAG_LEN = 7  # "</hint>"


@dataclass
class _Segment:
    language: str
    chunks: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)


class LanguageRouter:
    """Holds one TTS per language and synthesizes a tagged text stream with the right one."""

    def __init__(self) -> None:
        self._tts: dict[str, assemblyai.TTS] = {
            BASE_LANGUAGE: assemblyai.TTS(model="assemblyai-tts-1", voice=BASE_VOICE)
        }
        self._keepalive_task: asyncio.Task[None] | None = None

    def start_keepalive(self) -> None:
        if self._keepalive_task is None:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop(), name="tts-keepalive")

    async def aclose(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()

    async def _keepalive_loop(self) -> None:
        # livekit-plugins-assemblyai 1.8.12 assumes idle sessions never time out, so it sends no
        # KeepAlive. Its pool isn't public API, which is why requirements.txt pins the version.
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL_S)
            for tts in self._tts.values():
                # Includes a session held mid-reply while the learner has paused playback.
                for conn in list(tts._pool._connections):
                    if conn.usable:
                        conn.send(_KEEPALIVE_FRAME)

    @property
    def base_tts(self) -> assemblyai.TTS:
        return self._tts[BASE_LANGUAGE]

    def prewarm(self) -> None:
        """Open the English TTS session ahead of time so the greeting doesn't pay the handshake.

        Other languages connect on first use. Every session counts against the account's limit of
        new TTS sessions per minute (5 on a free plan), so opening all six up front hit the limit.
        """
        self.base_tts.prewarm()

    def _get(self, language: str) -> assemblyai.TTS:
        if language not in self._tts:
            self._tts[language] = assemblyai.TTS(
                model="assemblyai-tts-1",
                voice=BASE_VOICE if SAME_VOICE_FOR_ALL_LANGUAGES else NATIVE_VOICES[language],
                language=language,
            )
        return self._tts[language]

    async def synthesize(self, text: AsyncIterable[str]) -> AsyncIterator[rtc.AudioFrame]:
        segments: asyncio.Queue[_Segment | None] = asyncio.Queue()
        splitter = asyncio.create_task(_split_by_language(text, segments))
        try:
            while (segment := await segments.get()) is not None:
                async for frame in self._speak_segment(segment):
                    yield frame
        finally:
            # Also runs on interruption (the generator is closed), so no task outlives the turn.
            splitter.cancel()

    async def _speak_segment(self, segment: _Segment) -> AsyncIterator[rtc.AudioFrame]:
        stream = self._get(segment.language).stream()

        async def forward() -> None:
            while (chunk := await segment.chunks.get()) is not None:
                stream.push_text(chunk)
            stream.end_input()

        forwarder = asyncio.create_task(forward())
        try:
            async for event in stream:
                yield event.frame
        except APIError as e:
            # Keep speaking the rest of the reply rather than losing all of it to one segment.
            logger.warning("TTS failed for %s segment, skipping it: %s", segment.language, e)
        finally:
            forwarder.cancel()
            await stream.aclose()


async def _split_by_language(text: AsyncIterable[str], out: asyncio.Queue[_Segment | None]) -> None:
    """Parse `<xx>...</xx>` tags out of a token stream (tags may be split across tokens)."""
    current: _Segment | None = None
    language = BASE_LANGUAGE
    buffer = ""
    in_hint = False

    def emit(piece: str) -> None:
        nonlocal current
        if in_hint:
            return
        if not piece.strip() and current is None:
            return  # don't open a segment for leading whitespace
        if current is None:
            current = _Segment(language)
            out.put_nowait(current)
        current.chunks.put_nowait(piece)

    def switch(new_language: str) -> None:
        nonlocal current, language
        if new_language == language:
            return
        if current is not None:
            current.chunks.put_nowait(None)
        current, language = None, new_language

    try:
        async for chunk in text:
            buffer += chunk
            while buffer:
                lt = buffer.find("<")
                if lt == -1:
                    emit(buffer)
                    buffer = ""
                    break
                if lt > 0:
                    emit(buffer[:lt])
                    buffer = buffer[lt:]
                match = _TAG.match(buffer)
                if match:
                    closing, code = match.groups()
                    if code == "hint":
                        in_hint = not closing
                    elif closing:
                        switch(BASE_LANGUAGE)
                    elif code in NATIVE_VOICES:
                        switch(code)
                    # unknown language tags are dropped and spoken in the current language
                    buffer = buffer[match.end():]
                elif len(buffer) < _MAX_TAG_LEN and "<" not in buffer[1:]:
                    break  # might be the start of a tag; wait for more tokens
                else:
                    emit(buffer[0])  # a literal "<"
                    buffer = buffer[1:]
        if buffer:
            emit(buffer)
    finally:
        if current is not None:
            current.chunks.put_nowait(None)
        out.put_nowait(None)

