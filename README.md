# Language Tutor — a reference voice agent on AssemblyAI

A voice agent for language learners: you ask how to say something in Spanish, French, German,
Italian, or Portuguese, it teaches you the phrase in a **native voice for that language**, breaks
the tricky word down syllable by syllable, and listens to you try it.

Built as the reference implementation for a rip-and-replace evaluation: a customer running a
language-learning voice agent on another provider is deciding whether to move to AssemblyAI.
**The evaluation plan is in [`docs/evaluation-plan.md`](docs/evaluation-plan.md).**

The page has four tabs: **Language Tutor** (the reference agent), **Architecture** (a visual of
how it's built, below), **Evaluations** (how its
speech-to-text handles learners, from recorded clips; [below](#evaluation-recorded-clips-streamed-in-real-time)),
and **Extra Credit**, a game called *Stump the Interpreter* that shows off mixed-language speech
recognition ([below](#extra-credit-stump-the-interpreter)).

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

Open **http://localhost:8000** in Chrome, press **Enter** on the intro screen, press **Start**,
allow the microphone, and ask something like *"How do I say 'where is the train station' in German?"*

- **Pause** freezes the tutor mid-sentence and mutes your mic; **Resume** picks the sentence up
  where it stopped. To move on instead, just start talking: that interrupts it like any barge-in.
- The transcript highlights foreign phrases, and shows written pronunciation hints
  (e.g. *beeb-lee-oh-TEH-kah*) that are displayed but never spoken.
- **Cost & latency** (bottom right) shows the conversation so far: median and slowest
  voice-to-voice latency with its breakdown (end-of-turn detection, LLM first token, TTS first
  audio), and the estimated cost of each model at list price, in total and per minute. See
  [Cost and latency panel](#cost-and-latency-panel). The same latency numbers are logged to the
  terminal for every turn.

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
│ cost & latency panel     │                          │                          │
└───────────┬──────────────┘          WebRTC          │   └─► assemblyai.STT ────┼──► Streaming STT
            │ GET /token                              │        │ turn ended       │    (+ end-of-turn)
            ▼                                         │        ▼                  │
     server.py (page, room tokens,                    │   LLM (OpenAI-compatible)─┼──► LLM Gateway
       interpreter relay)                             │                           │
                                                      │        │ "<es>¿Dónde…?</es>"│
                                                      │        ▼                  │
                                                      │   language_tts.py ────────┼──► Streaming TTS
                                                      │   one session per language│    (Kyla, Constanza,
                                                      └──────────────────────────┘     Agathe, …)
```

| File | Role |
|---|---|
| `agent.py` | The agent: STT/LLM/TTS configuration, turn-taking, pause/resume and summary RPCs, latency metrics |
| `language_tts.py` | Splits the LLM's tagged reply by language and speaks each segment with that language's native voice; keeps idle TTS sessions alive; counts TTS characters for the cost estimate |
| `prompts.py` | The tutor's system prompt and greeting |
| `usage.py` | Per-conversation latency and estimated cost, with the list prices it uses |
| `server.py` | Serves the web page, mints LiveKit room tokens, serves evaluation results, and backs the interpreter: STT relay, translation fallback, TTS tokens |
| `web/index.html` | Single-file UI (no build step): intro screen, all four tabs, LiveKit browser SDK from a CDN |
| `evals/` | Real-time STT evaluation: clip list, guided recorder, runner, and the latest results |
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

**LiveKit Agents over the raw SDK or a fully managed agent.** The hard parts of a voice agent is plumbing together the different model calls: streaming, end-of-turn, barge-in, conversation
history. The LiveKit handles this, so moving to AssemblyAI is a change to two
plugin constructors, not a rewrite.

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


### Cost and latency panel

Built for the customer's evaluation: speed and cost per conversation are the two numbers they'll
compare against their current stack, so the demo shows them live instead of in a spreadsheet later.

- **Latency** comes from LiveKit, which attaches each turn's timings to the conversation history:
  voice to voice (learner stops talking → tutor audio starts), end-of-turn detection, LLM first
  token, TTS first audio. The panel shows the median and the slowest turn. The greeting isn't
  counted, since it answers nothing.
- **Cost** uses AssemblyAI list prices (checked November 2026, in `usage.py`):

  | Model | Billed on | Price |
  |---|---|---|
  | Streaming STT (`assemblyai-stt-3-7-realtime-agent`) | Minutes the session is open, paused time included | $0.45 / hour |
  | LLM Gateway (`gemma-4-31b`) | Input / output tokens, from LiveKit's LLM metrics | $0.14 / $0.40 per 1M tokens, +10% for the US in-region endpoint |
  | Streaming TTS (`assemblyai-tts-1`) | Characters sent to TTS, counted across every language's session | $15 per 1M characters |

  It's what the conversation would cost on a pay-as-you-go account; free-plan credits aren't applied.

---

## Evaluation: recorded clips, streamed in real time

A first pass at the offline replay in the [evaluation plan](docs/evaluation-plan.md#4-the-harness),
built around how a language tutor fails rather than general accuracy. Nine short clips (one
speaker: me) each test one failure mode. `evals/run.py` streams each one through the real-time
model in 50 ms chunks at speaking pace, exactly like the tutor's mic audio, under several
configurations, and checks the transcript. Same audio every run, so configurations are comparable.

```bash
python evals/record.py   # guided recording of the clips in evals/clips.py (audio isn't in the repo)
python evals/run.py      # streams them, prints pass/fail, writes evals/results.md
```

| Clip | Tests | Tutor | + taught words | Preset turn timing | + learner context | All 32 languages |
|---|---|---|---|---|---|---|
| "How do I say *biblioteca*…" | Foreign word in an English question | ✅ | – | ✅ | ✅ | ✅ |
| "Why is it *el perro* and not *la perro*?" | Same | ✅ | – | ✅ | ✅ | ✅ |
| "¿Dónde está la biblioteca?" | Correct attempt | ✅ | ✅ | ✅ | ✅ | ✅ |
| "¿Dónde está la **bibliotica**?" (wrong on purpose) | Wrong attempt must stay wrong | ❌ | ❌ | ❌ | ❌ | ❌ |
| "Eu preciso de um advogado." | Correct attempt (the "advocado" case) | ✅ | ✅ | ✅ | ✅ | ✅ |
| "Advogado." | One-word turn | ✅ | ✅ | ✅ | ✅ | ✅ |
| "我想去图书馆。" | Correct attempt, Mandarin | ❌ ¹ | ❌ ¹ | ❌ ¹ | ❌ ¹ | ✅ |
| "How do you say… um… the bill?" | Pauses mustn't end the turn | ✅ | – | ✅ | ✅ | ✅ |
| "…the *mercado*, *comprei umas frutas*, 但是太贵了" | Four languages, one sentence | ❌ ² | – | ❌ ³ | ❌ ² | ❌ ² |

"Tutor" is `agent.py`'s exact settings. "+ taught words" passes the word the tutor just taught as
`keyterms_prompt` (only for clips that follow a lesson). "+ learner context" adds a `prompt`
describing a learner who mispronounces words. Full transcripts are in
[`evals/results.md`](evals/results.md).

¹ Empty transcript: the tutor steers to its six languages, which don't include Mandarin. Expected.
² The Mandarin came out romanized, roughly as it sounds: "dan si, tai guela".
³ The turn ended after "compré unas frutas" (now in Spanish) and the rest was lost.

**What it found:**

- **The model "corrects" wrong attempts, and nothing I tried changes that.** A deliberate
  *bibliotica* was transcribed as "biblioteca" in every configuration, with word confidence 1.0
  (the same as the correct attempt). Key terms, a contextual prompt, and a prompt telling it not to
  correct (which the docs say isn't supported) all left it unchanged, without hurting the correct
  attempts. So speech-to-text tells the tutor *which words* the learner said, not *how well*: the
  tutor can confirm the right sentence, but it can't grade pronunciation. That's a requirement to
  scope separately (a pronunciation-assessment model), and to test on the incumbent too, since
  any STT trained to output real words probably behaves the same way.
- **Correct attempts and code-switched questions are solid.** Every correct Spanish and Portuguese
  attempt, the one-word turn, and both English questions with embedded foreign words came back
  right in every configuration. The live "advocado" error didn't reproduce on recorded audio.
- **Mandarin in the middle of a sentence is the weak spot.** Mandarin on its own is perfect once
  the model listens for it. Switched into mid-sentence after English and Portuguese, it came out
  as romanized sounds in every configuration.
- **Next step: let the customer test it themselves.** A "test it yourself" panel in that tab:
  type the phrase, record it or upload the customer's own learner recordings, and get the same
  real-time transcription and pass/fail as `evals/run.py`. In a real evaluation, the customer's
  own audio is what convinces them.

---

## Extra credit: Stump the Interpreter

A game in the second tab: say one sentence in as many languages as you can, and see whether
AssemblyAI keeps up. It transcribes you as you speak, translates the sentence into English,
colors each language in your original sentence, reads the translation back, and keeps score
(languages in your last sentence, best so far, translation time).

It shows the features the tutor doesn't use:

- **Code-switching across 32 languages.** No `language_codes`: the model listens for every
  language it supports and switches mid-sentence. (The tutor steers to six because its TTS speaks
  six; the interpreter only ever speaks English, so it doesn't need to.)
- **Translation inside the STT stream.** The `llm_gateway` connection parameter makes AssemblyAI
  run a prompt on each final turn and return the result as an `LLMGatewayResponse` on the same
  WebSocket, typically 0.4–1 s after the turn ends. No second API call in our code.
- **Language detection** (`language_detection=true`) labels each turn's language; it's used as
  the fallback when the LLM's reply can't be parsed.
- **TTS over HTTP from the browser** with a temporary token: one request per translation, played
  as it streams in.

**How it's built.** No LiveKit and no agent process: the page captures the mic as 16 kHz PCM
(an AudioWorklet), streams it over a WebSocket, and plays TTS with the Web Audio API.

```
 mic ─► page ─► server.py /interpreter/ws ─► Streaming STT (+ translation prompt) ─┐
                                                                                  │ Turn, LLMGatewayResponse
 speakers ◄─ page ◄─ TTS HTTP API (Kyla, temporary token) ◄─ English ◄────────────┘
```

**Decisions and findings:**

- **Temporary tokens stop translating after 10 turns.** The page first connected to AssemblyAI
  directly with a temporary token (the documented way for browsers). After a few sentences,
  translations stopped arriving. Tested with a 16-sentence clip: a token session returned exactly
  10 `LLMGatewayResponse` messages and then none, even with the next sentences 30+ s later (so not
  a per-minute limit), and even with a token minted with a higher LLM Gateway `rpm`. The same
  session authenticated with the API key translated all 16. This isn't in the docs, so it's worth
  reporting. The fix: `server.py` relays the STT WebSocket and adds the API key and the
  translation prompt server-side. The key still never reaches the page, and translation stays
  inside the STT stream. The relay passed the same 16-sentence test with 16 translations.
- **A translation that never arrives doesn't hang the page.** The docs say a failed or timed-out
  translation sends nothing. If no translation arrives within 4 s, the page asks
  `/interpreter/translate`, which runs the same prompt against LLM Gateway directly; the card is
  marked "via fallback".
- **Per-language colors come from the LLM, not the STT model.** Language detection labels a whole
  turn, not each word, so the translation prompt also returns the sentence split into language
  segments. The page says which is which.
- **TTS speaks 6 languages; STT understands 32.** Verified against the live API: `japanese`,
  `mandarin` and `korean` return `422 not in supported set`. A learner of Japanese can be
  understood but not spoken to. The architecture already isolates TTS per language, so routing
  other languages to a third-party TTS is a contained change. Covered in the evaluation plan.

