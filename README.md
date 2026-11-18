# Language Tutor — a reference voice agent on AssemblyAI

A voice agent for language learners: you ask how to say something in Spanish, French, German,
Italian, or Portuguese, it teaches you the phrase in a **native voice for that language**, breaks
the tricky word down syllable by syllable, and listens to you try it.

Built as the reference implementation for a rip-and-replace evaluation: a customer running a
language-learning voice agent on another provider is deciding whether to move to AssemblyAI.
**The evaluation plan is in [`docs/evaluation-plan.md`](docs/evaluation-plan.md).**

Every model in the loop runs on one AssemblyAI API key:

| Stage | What | Model |
|---|---|---|
| Speech-to-text | AssemblyAI Streaming STT | `assemblyai-stt-3-7-realtime-agent` |
| Turn detection | AssemblyAI (end-of-turn from the STT model) | same |
| LLM | AssemblyAI LLM Gateway | `gemma-4-31b` |
| Text-to-speech | AssemblyAI Streaming TTS | `assemblyai-tts-1`, one native voice per language |
| Orchestration | [LiveKit Agents](https://docs.livekit.io/agents/) (open source) | — |

---

## Run it

Requirements: macOS or Linux, Python 3.13, [Homebrew](https://brew.sh) (for the local LiveKit
server), an AssemblyAI API key. Use headphones so the agent doesn't hear itself.

```bash
brew install livekit                      # local WebRTC server, no account needed
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                      # then paste your key after ASSEMBLYAI_API_KEY=
./run.sh                                  # starts LiveKit server + agent + web UI
```

Open **http://localhost:8000**, press **Start**, allow the microphone, and ask something like
*"How do I say 'where is the train station' in German?"*

- **Pause** freezes the tutor mid-sentence and mutes your mic; **Resume** picks the sentence up
  where it stopped. To move on instead, just start talking: that interrupts it like any barge-in.
- The transcript highlights foreign phrases, and shows written pronunciation hints
  (e.g. *beeb-lee-oh-TEH-kah*) that are displayed but never spoken.
- Per-turn latency (end-of-turn delay, LLM time-to-first-token, TTS time-to-first-byte) is logged
  to the terminal for every turn.

`run.sh` runs three processes, which you can also start separately:
`livekit-server --dev`, `python agent.py dev`, `python server.py`.

---

## How it's built

```
 Browser (web/index.html)          your machine                                   AssemblyAI
┌──────────────────────────┐   ┌─────────────────┐   ┌──────────────────────────┐
│ Start / Pause / Resume   │◄─►│ livekit-server  │◄─►│ agent.py (LiveKit Agents)│
│ live transcript          │   │ (local, --dev)  │   │                          │
│ agent state orb          │   └─────────────────┘   │ mic ─► Silero VAD (local)│
└───────────┬──────────────┘          WebRTC          │   └─► assemblyai.STT ────┼──► Streaming STT
            │ GET /token                              │        │ turn ended       │    (+ end-of-turn)
            ▼                                         │        ▼                  │
     server.py (page + room tokens)                   │   LLM (OpenAI-compatible)─┼──► LLM Gateway
                                                      │        │ "<es>¿Dónde…?</es>"│
                                                      │        ▼                  │
                                                      │   language_tts.py ────────┼──► Streaming TTS
                                                      │   one session per language│    (Kyla, Constanza,
                                                      └──────────────────────────┘     Agathe, …)
```

| File | Role |
|---|---|
| `agent.py` | The agent: STT/LLM/TTS configuration, turn-taking, pause/resume RPC, latency metrics |
| `language_tts.py` | Splits the LLM's tagged reply by language and speaks each segment with that language's native voice; keeps idle TTS sessions alive |
| `prompts.py` | The tutor's system prompt and greeting |
| `server.py` | Serves the web page and mints LiveKit room tokens |
| `web/index.html` | Single-file UI (no build step), LiveKit browser SDK from a CDN |
| `run.sh` | Starts all three processes; Ctrl+C stops them |

### One turn

1. Mic audio streams to AssemblyAI. The STT model handles English questions with foreign words
   mixed in (*"why is it **el perro** and not **la perro**?"*), steered to the six languages the
   product supports.
2. AssemblyAI's model decides when the learner has finished their thought and emits the final
   transcript. LiveKit adds no extra delay on top.
3. LiveKit sends the history plus the tutor prompt to LLM Gateway; the reply streams back.
4. The reply carries language tags: `In German, that's <de>Wo ist der Bahnhof?</de>`.
   `language_tts.py` parses the stream as it arrives and sends each segment to the TTS session
   for its language. English starts speaking on the first tokens; a switch only waits for the
   closing tag.
5. If the learner talks over the tutor, local VAD catches it immediately and playback stops.

---

## Key decisions

Each of these was a choice between options; the reasoning is the part worth reading.

**LiveKit Agents over the raw SDK or a fully managed agent.** The hard parts of a voice agent are
not the model calls but the plumbing between them: streaming, end-of-turn, barge-in, conversation
history. A framework handles those, and, more importantly for this deal, a customer evaluating a
switch most likely already runs on one. With LiveKit, moving to AssemblyAI is a change to two
plugin constructors, not a rewrite. The one piece specific to language learning (per-language
TTS) slots into LiveKit's `tts_node` override without fighting the framework.

**The newest STT model, set explicitly.** AssemblyAI's docs recommend
`assemblyai-stt-3-7-realtime-agent` for voice agents; the LiveKit plugin still defaults to the
previous model, so it is set explicitly. `language_codes` steers native code-switching to exactly
the six languages the whole pipeline supports.

**Turn-taking tuned for learners, not call-center callers.** The `balanced` preset ends a turn
after only 128 ms of silence following a period. In testing, *"Wait, I'm sorry. I'm confused. Can
you teach me…"* became three turns, and the tutor started answering "Wait, I'm sorry." The logs
confirmed it (`stt end of speech received while vad is still in a speech segment`). Learners
pause constantly — to find a word, to work up to a phrase — so `min_turn_silence` is raised to
600 ms and `max_turn_silence` to 2000 ms. Trade-off: replies start ~0.5 s later after a
sentence-final pause. Worth it for this audience; a configuration a customer would tune per
product.

**Language tags and a native voice per language.** AssemblyAI TTS doesn't detect language: a
session speaks the language it was opened with. A tutor reply mixes languages in every sentence,
so read by an English session, the Spanish comes out with an English accent — the one thing a
pronunciation tutor can't do. The LLM wraps foreign phrases in `<es>…</es>` (and `<fr>`, `<de>`,
`<it>`, `<pt>`), and `language_tts.py` routes each segment to a TTS session for that language.
- *Tried and rejected:* one voice (Kyla) told to speak Spanish, to avoid a voice change mid-reply.
  It sounded clearly worse; AssemblyAI's docs warn that voices sound best in their own language.
- *Voices:* all female, native to their language, chosen by ear: Kyla (en), Constanza (es),
  Agathe (fr), Magdalena (de), Giada (it), Iara (pt).

**Teach pronunciation with audio, not respellings.** The first prompt had the tutor say
"beeb-lee-oh-TEH-kah", which an English voice reads out as nonsense. Now the native voice says
the word slowly by syllable, then whole (`<es>bi... blio... te... ca... biblioteca</es>`;
ellipses produce pauses per AssemblyAI's TTS prompting guide), and the written respelling goes in
a `<hint>` tag that the transcript shows but the TTS never receives.

**LLM chosen by measurement.** Time-to-first-token is the latency a voice user feels most, so
candidates were timed on a real tutor question through LLM Gateway (3 runs each, median):

| Model | First token | Answer quality |
|---|---|---|
| `gemma-4-31b` | 0.57 s | Correct phrase and pronunciation, no markdown, follows the teaching format |
| `qwen3.5-4b-32k-fast` | 0.14 s | 4× faster, but a wrong pronunciation hint and stray markdown |

For a pronunciation tutor, a fast wrong answer is worse than a slightly slower right one. (Only
these two models were available on the free plan used for this build; Claude, GPT and Gemini
models on the Gateway are worth benchmarking the same way on a paid account. The model is set by
`LLM_MODEL` in the environment.)

**Pause means pause.** The button freezes playback mid-sentence (LiveKit's audio output supports
true pause/resume) instead of discarding the rest of the reply. A learner who steps away and
comes back hears the end of the phrase; a learner who wants to move on just talks.

---

## Limitations and what I found along the way

- **TTS speaks 6 languages; STT understands 32.** Verified against the live API: `japanese`,
  `mandarin` and `korean` return `422 not in supported set`. A learner of Japanese can be
  understood but not spoken to. The architecture already isolates TTS per language, so routing
  other languages to a third-party TTS is a contained change. Covered in the evaluation plan.
- **Free plan: 5 new TTS sessions per minute.** The first version opened all six language
  sessions at startup and hit the limit (`asked to wait 19.0s before opening a session`); now
  only English opens up front and the rest connect on first use. Paid plans start at 200/minute
  and scale with use, so this is a dev-only constraint, but the design lesson (one session per
  language per conversation, reused) holds at any scale.
- **Idle TTS sessions close after 120 s, and the LiveKit plugin sends no KeepAlive.** Its code
  assumes idle sessions never time out. That caused reconnect delays and lost speech after long
  pauses. `language_tts.py` sends a `KeepAlive` every 60 s on every open session; verified with a
  3m43s pause and zero closures. This reaches into the plugin's connection pool, so the plugin
  version is pinned; worth reporting upstream.
- **Word-level transcript alignment is off.** Speaking one reply over several TTS sessions means
  LiveKit falls back to its own text/audio sync, so after a barge-in the saved history may contain
  a few words the learner didn't actually hear.
- **A correct pronunciation can be transcribed as wrong.** In testing, *advogado* was transcribed
  as "advocado" five times in a row, so the tutor kept correcting a learner who may have said it
  right. This is the highest-stakes failure mode for the product; the evaluation plan builds a
  test set around it.
- **No LLM fallback yet.** One request in testing got no response for 10 s before LiveKit retried.
  Next step: a shorter timeout plus an LLM Gateway fallback model.
- **Local only.** `livekit-server --dev` uses fixed dev credentials and binds to localhost. A
  deployment would use LiveKit Cloud or a self-hosted server with real keys, and mint browser
  tokens server-side as `server.py` does.
