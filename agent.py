"""Language-learning voice agent: AssemblyAI STT + LLM Gateway + TTS, orchestrated by LiveKit Agents.

Run with `python agent.py dev` (connects to the LiveKit server in LIVEKIT_URL and joins every new room).
"""

import json
import logging
import os

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    TurnHandlingOptions,
    cli,
)
from livekit.plugins import assemblyai, openai, silero

from language_tts import NATIVE_VOICES, LanguageRouter
from prompts import GREETING, TUTOR_INSTRUCTIONS

load_dotenv()
logger = logging.getLogger("tutor")

# Silero (local, used for barge-in) and AssemblyAI's server-side VAD should agree on what
# counts as speech, otherwise there's a "dead zone" where one hears speech and the other doesn't.
VAD_THRESHOLD = 0.2

TUTOR_LANGUAGES = list(NATIVE_VOICES)  # es, fr, de, it, pt

# Chosen by measuring time-to-first-token and answer quality on LLM Gateway (see README).
LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-31b")


class Tutor(Agent):
    def __init__(self, router: LanguageRouter) -> None:
        super().__init__(instructions=TUTOR_INSTRUCTIONS)
        self._router = router

    def tts_node(self, text, model_settings):
        # The LLM wraps foreign phrases in <es>...</es>; speak each segment in its own language.
        return self._router.synthesize(text)

    async def on_enter(self) -> None:
        # A fixed greeting plays immediately instead of waiting on the LLM.
        self.session.say(GREETING)


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=VAD_THRESHOLD)


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    api_key = os.environ["ASSEMBLYAI_API_KEY"]

    router = LanguageRouter()
    router.prewarm()  # English only; other languages connect on first use (see LanguageRouter)
    router.start_keepalive()  # hold idle TTS sessions open (AssemblyAI closes them after 120 s)
    ctx.add_shutdown_callback(router.aclose)

    session = AgentSession(
        stt=assemblyai.STT(
            model="assemblyai-stt-3-7-realtime-agent",
            # Learners speak English and attempt the language they're learning; steer the model's
            # code-switching to exactly the six languages the full pipeline (STT + TTS) supports.
            language_codes=["en", *TUTOR_LANGUAGES],
            mode="balanced",
            # Language learners pause a lot: to find a word, or between "Wait, sorry." and the
            # real question. Balanced mode ends the turn after just 128 ms of silence following
            # a period, which split one thought into several turns and made the tutor reply mid-thought.
            # Trade-off: replies start ~0.5 s later after a sentence-final pause.
            min_turn_silence=600,
            # Without terminal punctuation (trailing off, "how do you say... um"), wait longer
            # before forcing the turn to end. Balanced default is 1280 ms.
            max_turn_silence=2000,
            vad_threshold=VAD_THRESHOLD,
        ),
        llm=openai.LLM(
            model=LLM_MODEL,
            base_url="https://llm-gateway.assemblyai.com/v1",
            api_key=api_key,
        ),
        tts=router.base_tts,
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            # AssemblyAI's model decides when the user has finished their thought...
            turn_detection="stt",
            # ...so LiveKit shouldn't stack its own delay on top.
            endpointing={"min_delay": 0},
        ),
        tts_text_transforms=["filter_emoji", "filter_markdown"],
        # Our tts_node yields plain audio across several TTS sessions, so transcript timing
        # comes from LiveKit's own text/audio sync rather than per-word TTS timestamps.
        use_tts_aligned_transcript=False,
    )

    # Pause/Resume button in the web UI. Pause freezes the tutor mid-sentence and stops listening;
    # Resume picks the sentence up where it left off. If the learner would rather move on,
    # they just start talking, which interrupts the tutor like any other barge-in.
    async def set_paused(data: rtc.RpcInvocationData) -> str:
        paused = json.loads(data.payload).get("paused", False)
        logger.info("paused=%s", paused)
        audio_out = session.output.audio
        if paused:
            if audio_out and audio_out.can_pause:
                audio_out.pause()
            else:
                session.interrupt()  # fallback: no pausable output, so stop instead
        elif audio_out and audio_out.can_pause:
            audio_out.resume()
        session.input.set_audio_enabled(not paused)
        return "ok"

    await session.start(agent=Tutor(router), room=ctx.room)
    # Registering requires a connected room, which session.start() takes care of.
    ctx.room.local_participant.register_rpc_method("set_paused", set_paused)


if __name__ == "__main__":
    cli.run_app(server)
