"""Per-conversation latency and estimated cost, shown in the web UI's summary panel.

Prices are AssemblyAI list prices (https://www.assemblyai.com/pricing, checked 2026-11-17).
The estimate is what this conversation would cost on a pay-as-you-go account; free-plan
credits aren't taken into account.
"""

import statistics
import time

from livekit.agents import metrics

# Real-time STT is billed on how long the session is open, not on audio sent
# (so paused time counts too).
STT_PER_HOUR = 0.45  # assemblyai-stt-3-7-realtime-agent
TTS_PER_MILLION_CHARS = 15.00  # assemblyai-tts-1
# LLM Gateway, per 1M tokens (input, output). The US endpoint used here is an in-region
# endpoint, which costs 10% more than global routing.
LLM_PER_MILLION_TOKENS = {
    "gemma-4-31b": (0.14, 0.40),
    "qwen3.5-4b-32k-fast": (0.10, 0.50),
}
LLM_IN_REGION_SURCHARGE = 1.10


class ConversationStats:
    def __init__(self, llm_model: str) -> None:
        self._llm_model = llm_model
        self._started_at = time.monotonic()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tts_characters = 0  # counted by LanguageRouter, across every language's TTS
        # One entry per tutor reply that answered the learner (the greeting isn't a reply).
        self._turns: list[dict[str, float]] = []
        self._pending_end_of_turn: float | None = None

    def on_metrics(self, m: metrics.AgentMetrics) -> None:
        if isinstance(m, metrics.LLMMetrics):
            self.prompt_tokens += m.prompt_tokens
            self.completion_tokens += m.completion_tokens

    def on_message(self, message) -> None:
        """Called for each conversation item; per-turn latency is attached to the messages."""
        role = getattr(message, "role", None)  # items also include agent handoffs, tool calls
        report = getattr(message, "metrics", None) or {}
        if role == "user":
            self._pending_end_of_turn = report.get("end_of_turn_delay")
        elif role == "assistant" and "e2e_latency" in report:
            self._turns.append({
                "total": report["e2e_latency"],
                "end_of_turn": self._pending_end_of_turn,
                "llm_first_token": report.get("llm_node_ttft"),
                "tts_first_audio": report.get("tts_node_ttfb"),
            })
            self._pending_end_of_turn = None

    def summary(self) -> dict:
        minutes = (time.monotonic() - self._started_at) / 60
        llm_in, llm_out = LLM_PER_MILLION_TOKENS.get(self._llm_model, (0.0, 0.0))
        cost = {
            "stt": minutes / 60 * STT_PER_HOUR,
            "llm": (self.prompt_tokens * llm_in + self.completion_tokens * llm_out)
            / 1e6 * LLM_IN_REGION_SURCHARGE,
            "tts": self.tts_characters / 1e6 * TTS_PER_MILLION_CHARS,
        }
        cost["total"] = sum(cost.values())

        def stat(key: str) -> dict | None:
            values = [t[key] for t in self._turns if t.get(key) is not None]
            if not values:
                return None
            return {"median": statistics.median(values), "max": max(values)}

        return {
            "minutes": minutes,
            "turns": len(self._turns),
            "latency": {k: stat(k) for k in ("total", "end_of_turn", "llm_first_token", "tts_first_audio")},
            "usage": {
                "stt_minutes": minutes,
                "llm_model": self._llm_model,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "tts_characters": self.tts_characters,
            },
            "cost": cost,
            "cost_per_minute": cost["total"] / minutes if minutes else 0.0,
        }
