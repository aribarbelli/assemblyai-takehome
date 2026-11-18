# AssemblyAI Take-Home: Language-Learning Voice Agent

Reference voice agent on AssemblyAI for a language-learning customer (users ask how to say words/phrases in another language; the agent teaches them).

## AssemblyAI docs

Before writing AssemblyAI code, read https://www.assemblyai.com/docs/agent-instructions.md
and https://www.assemblyai.com/docs/llms.txt. The API has changed — do not rely on
memorized parameter names. Use the `assemblyai-docs` MCP server for mid-task doc lookups.

## Environment

- Python 3.13, virtualenv at `.venv/` (`source .venv/bin/activate`), deps pinned in `requirements.txt`.
- API key in `.env` as `ASSEMBLYAI_API_KEY` (gitignored; never commit or print it).
- Streaming STT in the installed SDK (assemblyai 1.10.11) is `assemblyai.streaming.v3.StreamingClient`.
