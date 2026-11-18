# Winning the technical evaluation

**The situation:** the customer runs a voice agent for language learners on another provider and
is evaluating a switch to AssemblyAI. A rip-and-replace is won or lost on two questions:

1. **Is it measurably better for *our* users?** Not on a public benchmark: on our learners, our
   languages, our failure modes.
2. **Is switching cheap and safe?** Engineering time, migration risk, and what happens when
   something is worse.

The plan below answers both with the customer's own data, on a two-week proof of concept, with
success criteria agreed before any results exist.

---

## 1. Discovery (before the POC starts)

What I'd ask, and why each answer changes the plan:

| Question | Why it matters |
|---|---|
| What's your stack today? STT, LLM, TTS, orchestration (LiveKit / Pipecat / custom)? | Decides the migration path. On a framework, switching STT/TTS is a plugin swap (see §6). |
| Which language pairs, by share of sessions? What are learners' native languages? | Weights the test set. Spanish for English speakers is a different test than Portuguese for Spanish speakers. |
| What do users complain about today? | The pain points become the headline metrics. For this product I'd expect: *"it said I was wrong when I was right,"* *"it cut me off,"* *"it sounds robotic in Spanish."* |
| Which product metrics do you watch? (lesson completion, retries per phrase, session length) | The final A/B is judged on these, not on WER. |
| Do you know the lesson's target language and vocabulary before the learner speaks? | If yes, it's a big accuracy lever (§5). Most lesson-based apps do. |
| Platform: mobile app, web, phone? Noisy environments? Children? | Audio conditions for the test set; children also bring data retention and consent requirements. |
| Volume and current cost per conversation minute? | Cost comparison on real usage. |
| Data residency, retention, compliance? | AssemblyAI has US and EU endpoints for STT and TTS; confirm before the POC, not after. |

---

## 2. Success criteria, agreed up front

A scorecard both sides sign off on before any testing. Targets are relative to the incumbent
measured on the same audio, not absolute numbers.

| Metric | Why it matters for language learners | How it's measured |
|---|---|---|
| **False rejection rate** on target words | The learner says the word *correctly* and the transcript says otherwise, so the tutor corrects them. Most damaging failure for this product; I hit it while building (*advogado* → "advocado", 5 times). | Attempts labeled correct by native-speaker teachers; % whose transcript doesn't contain the target word |
| **False acceptance rate** on target words | The opposite: a *wrong* attempt gets "auto-corrected" into the right word, so the learner is never told. A very smart STT can be too smart here. | Attempts labeled incorrect; % transcribed as the target word |
| Accuracy on code-switched turns | Learners ask in English with foreign words inside: *"why is it **el perro** and not **la perro**?"* | WER, plus exact-match on the embedded foreign words |
| WER on learner speech, per language | Non-native accents in both directions | Standard WER on labeled set |
| Premature end-of-turn rate | Learners pause mid-thought; being cut off is frustrating and the tutor answers a half-question | % of multi-sentence or hesitant turns split into 2+ turns |
| Voice-to-voice latency, p50/p95 | Time from learner stops speaking → tutor audio starts | End-of-turn delay + LLM TTFT + TTS TTFB (the reference agent logs all three per turn) |
| TTS pronunciation quality | The tutor's voice *is* the pronunciation lesson | Blind listening test by native speakers, per language, 1–5 rating (MOS) |
| Barge-in reliability | Learners interrupt to try the phrase | % of interruptions where playback stops within ~300 ms; false barge-ins from noise |
| Reliability | | Error and reconnect rate over the POC traffic |
| Cost per conversation minute | | STT + LLM + TTS, at their volume |

**False rejection and false acceptance pull in opposite directions.** Boosting the lesson
vocabulary (§5) lowers false rejections but can raise false acceptances. The scorecard shows
both, so the customer picks the operating point on purpose instead of discovering it in reviews.

---

## 3. The test set

Built from the customer's audio (production recordings with consent, or a short scripted
collection with their learners), labeled by native-speaker teachers. Starting size: ~200
utterances per language pair, weighted by session share.

| Bucket | Example | Tests |
|---|---|---|
| Questions with embedded target words | "How do I say *biblioteca*?" / "Is it *el* or *la computadora*?" | Code-switching |
| Learner attempts, **correct** | *"¿Dónde está la biblioteca?"* with an accent | False rejection |
| Learner attempts, **incorrect** | *"¿Dónde está la bibliotica?"* | False acceptance |
| Hesitant speech | "How do you say… um… the thing where you… *the bill*?" | Premature end-of-turn |
| Single-word turns | "*Perro.*" | Short-utterance accuracy |
| Real-world conditions | Kitchen, bus, kids in the background | Noise robustness |

---

## 4. The harness

Two complementary tests, both run on AssemblyAI **and** the incumbent:

**Offline replay (most of the scorecard).** A script streams every test file through each
provider's real-time STT, paced at real time with the production settings, and scores the
results against the labels. Same audio, same conditions, reproducible, and rerunnable after each
tuning change. Turn segmentation comes from the same run.

**Live A/B with the reference agent (latency and feel).** The agent in this repo, with STT and TTS
selectable by configuration, so the same conversation flow runs on either stack. LiveKit's
per-turn metrics give the latency breakdown. The customer's own team uses both and reports which
feels better: subjective, but it's often what decides a deal.

**Blind TTS listening test.** The same phrases synthesized by both providers, shuffled, rated by
native speakers per language.

---

## 5. Tuning levers I'd use during the POC

What makes this use case different, and the AssemblyAI settings that address it. Each change is
measured on the scorecard, not assumed.

- **Narrow the languages per session.** The app knows the learner is in a Spanish lesson, so pass
  `language_codes=["en", "es"]` instead of all six. Fewer languages to confuse.
- **Lesson vocabulary as key terms.** The words in today's lesson are known in advance; pass them
  as `keyterms_prompt` and update them mid-session as the lesson moves on. This should cut false
  rejections like *advogado*; watch false acceptance.
- **Context carryover.** The STT model receives the tutor's last reply, so after the tutor says
  *biblioteca*, the learner's attempt is transcribed with that context. On by default in the
  reference agent; measure how much it helps.
- **Turn silence values.** The reference agent uses 600 ms / 2000 ms instead of the 128 ms /
  1280 ms preset because learners pause. Sweep these on the hesitant-speech bucket and pick the
  best trade between being cut off and waiting.
- **Voice focus** for noisy mobile use, if the noise bucket shows a problem.
- **Voice choice per language.** The customer picks voices by ear from the catalog, as I did for
  the reference agent.

---

## 6. Migration path: make switching cheap and safe

**The code change.** If they're on LiveKit (or Pipecat, which has equivalent AssemblyAI support),
the swap is configuration:

```python
session = AgentSession(
    stt=assemblyai.STT(model="assemblyai-stt-3-7-realtime-agent", language_codes=["en", "es"]),
    tts=assemblyai.TTS(model="assemblyai-tts-1", voice="aai-constanza", language="es"),
    llm=...,  # unchanged, or LLM Gateway to consolidate on one key and one bill
    ...
)
```

The rest of their app (prompts, tools, UI, telephony) stays as it is.

**The rollout,** each stage gated on the scorecard:
1. **Shadow mode.** Stream live audio to AssemblyAI STT in parallel with the incumbent; log both
   transcripts and compare. No user impact; real-traffic results in days.
2. **Small A/B.** 5% of sessions on AssemblyAI end to end. Judge on the customer's product
   metrics: retries per phrase, lesson completion, session length.
3. **Ramp** by language pair, starting where the scorecard was strongest.

Rollback at any stage is a configuration change.

---

## 7. Gaps, stated up front

In a rip-and-replace, the customer's engineers will find the gaps; better that they hear them
from me first, with a plan.

| Gap | Impact | Plan |
|---|---|---|
| **TTS speaks 6 languages** (en, es, fr, de, it, pt) while STT understands 32 | Learners of Japanese, Mandarin, Korean, etc. can be understood but not spoken to | Route those languages to their current TTS. The reference agent already runs one TTS per language, so this is a routing table entry, not a redesign. Ask for the TTS language roadmap. |
| TTS doesn't detect language; one session speaks one language | Mixed-language replies need per-segment routing | Solved in the reference agent (`language_tts.py`): LLM tags + a session per language. Hand this over as code they can reuse. |
| LiveKit plugin sends no TTS `KeepAlive` | Idle sessions drop after 120 s: reconnect delay, lost audio after long pauses | Fixed in the reference agent; report upstream so the plugin fixes it for everyone. |
| Temporary-token STT sessions stop returning built-in translations after 10 turns (found building the extra-credit interpreter; not documented) | A browser app using real-time translation the documented way breaks silently mid-conversation | Relay the session server-side with the API key (done in `server.py`); report it and get it fixed or documented |
| Word-level transcript alignment lost with multiple TTS sessions | After a barge-in, history may include a few unheard words | Minor; acceptable, or fixable by merging word timings across sessions. |

---

## 8. Timeline and readout

**Week 1:** discovery, test set collection and labeling, harness, incumbent baseline.
**Week 2:** AssemblyAI runs, tuning (§5), blind TTS test, live A/B sessions with their team.
**Readout:** the scorecard side by side, audio clips of wins *and* losses, cost at their volume,
and a recommendation by language pair: switch, switch with tuning, or keep the incumbent for
that piece.

A recommendation that says "keep your current TTS for Japanese" is what makes the rest of the
scorecard credible.
