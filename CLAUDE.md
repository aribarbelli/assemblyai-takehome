# AssemblyAI Take-Home: Language-Learning Voice Agent

Reference voice agent on AssemblyAI for a language-learning customer (users ask how to say words/phrases in another language; the agent teaches them).

## AssemblyAI docs

Before writing AssemblyAI code, read https://www.assemblyai.com/docs/agent-instructions.md
and https://www.assemblyai.com/docs/llms.txt. The API has changed — do not rely on
memorized parameter names. Use the `assemblyai-docs` MCP server for mid-task doc lookups.

## Environment

- Python 3.13, virtualenv at `.venv/` (`source .venv/bin/activate`), deps pinned in `requirements.txt`.
- API key in `.env` as `ASSEMBLYAI_API_KEY` (gitignored; never commit or print it).
- Orchestration: LiveKit Agents 1.8.12 with `livekit-plugins-assemblyai` (`assemblyai.STT`, `assemblyai.TTS`); LLM via LLM Gateway through `livekit.plugins.openai` (base URL `https://llm-gateway.assemblyai.com/v1`). One AssemblyAI key covers all three.
- STT model: `assemblyai-stt-3-7-realtime-agent` (current recommendation for voice agents; the plugin defaults to `universal-3-6-pro`, so set it explicitly).
- TTS speaks only en/es/de/fr/it/pt and does not detect language — `language` must be set per session.
