# STT evaluation results

Run 2026-11-18 00:28. 9 clips recorded by one speaker, streamed in real time through `assemblyai-stt-3-7-realtime-agent`. See `evals/clips.py` for the checks and `docs/evaluation-plan.md` for why each one matters.

| Clip | What it tests | tutor | tutor + taught words | preset turn timing | tutor + learner context | all 32 languages |
|---|---|---|---|---|---|---|
| `question_biblioteca` | Question with an embedded foreign word | ✅ | – | ✅ | ✅ | ✅ |
| `question_el_perro` | Question with an embedded foreign word | ✅ | – | ✅ | ✅ | ✅ |
| `attempt_es_correct` | Learner attempt, correct | ✅ | ✅ | ✅ | ✅ | ✅ |
| `attempt_es_wrong` | Learner attempt, incorrect (false acceptance) | ❌ missing 'bibliotica'; auto-corrected to 'biblioteca' | ❌ missing 'bibliotica'; auto-corrected to 'biblioteca' | ❌ missing 'bibliotica'; auto-corrected to 'biblioteca' | ❌ missing 'bibliotica'; auto-corrected to 'biblioteca' | ❌ missing 'bibliotica'; auto-corrected to 'biblioteca' |
| `attempt_pt_correct` | Learner attempt, correct (the 'advocado' case) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `single_word_advogado` | Single-word turn | ✅ | ✅ | ✅ | ✅ | ✅ |
| `attempt_zh_correct` | Learner attempt, correct (Mandarin) | ❌ missing '图书馆' | ❌ missing '图书馆' | ❌ missing '图书馆' | ❌ missing '图书馆' | ✅ |
| `hesitant` | Hesitant speech (premature end-of-turn) | ✅ | – | ✅ | ✅ | ✅ |
| `mixed_four_languages` | Code-switching, four languages | ❌ missing '太贵' | – | ❌ missing 'comprei'; missing '太贵' | ❌ missing '太贵' | ❌ missing '太贵' |
| **Passed** | | **6/9** | **3/5** | **6/9** | **6/9** | **7/9** |

## Transcripts

**`question_biblioteca`**, said: How do I say biblioteca in a sentence?

- tutor: “How do I say biblioteca in a sentence?”
- preset turn timing: “How do I say biblioteca in a sentence?”
- tutor + learner context: “How do I say biblioteca in a sentence?”
- all 32 languages: “How do I say biblioteca in a sentence?”

**`question_el_perro`**, said: Why is it el perro and not la perro?

- tutor: “Why is it el perro and not la perro?”
- preset turn timing: “Why is it el perro and not la perro?”
- tutor + learner context: “Why is it el perro and not la perro?”
- all 32 languages: “Why is it el perro and not la perro?”

**`attempt_es_correct`**, said: ¿Dónde está la biblioteca?

- tutor: “¿Dónde está la biblioteca?”
- tutor + taught words: “¿Dónde está la biblioteca?”
- preset turn timing: “¿Dónde está la biblioteca?”
- tutor + learner context: “¿Dónde está la biblioteca?”
- all 32 languages: “¿Dónde está la biblioteca?”

**`attempt_es_wrong`**, said: ¿Dónde está la bibliotica?   (say it wrong on purpose: bib-lio-TI-ca)

- tutor: “¿Dónde está la biblioteca?”
- tutor + taught words: “¿Dónde está la biblioteca?”
- preset turn timing: “¿Dónde está la biblioteca?”
- tutor + learner context: “¿Dónde está la biblioteca?”
- all 32 languages: “¿Dónde está la biblioteca?”

**`attempt_pt_correct`**, said: Eu preciso de um advogado.

- tutor: “Eu preciso de um advogado.”
- tutor + taught words: “Eu preciso de um advogado.”
- preset turn timing: “Eu preciso de um advogado.”
- tutor + learner context: “Eu preciso de um advogado.”
- all 32 languages: “Eu preciso de um advogado.”

**`single_word_advogado`**, said: Advogado.

- tutor: “Advogado.”
- tutor + taught words: “Advogado.”
- preset turn timing: “Advogado.”
- tutor + learner context: “Advogado.”
- all 32 languages: “Advogado.”

**`attempt_zh_correct`**, said: 我想去图书馆。   (Wǒ xiǎng qù túshūguǎn)

- tutor: (nothing)
- tutor + taught words: (nothing)
- preset turn timing: (nothing)
- tutor + learner context: (nothing)
- all 32 languages: “我想去图书馆。”

**`hesitant`**, said: How do you say... um... the thing you pay at a restaurant... the bill?   (pause ~1 s at each '...')

- tutor: “How do you say, um, the thing you pay at a restaurant? The bill?”
- preset turn timing: “How do you say, um, the thing you pay at a restaurant? The bill?”
- tutor + learner context: “How do you say, um, the thing you pay at a restaurant? The bill?”
- all 32 languages: “How do you say, um, the thing you pay at a restaurant? The bill?”

**`mixed_four_languages`**, said: Yesterday I went to the mercado, comprei umas frutas, 但是太贵了.

- tutor: “Yesterday I went to the mercado, comprei umas frutas, dan si, tai guela.”
- preset turn timing: “Yesterday I went to the mercado, compré unas frutas.”
- tutor + learner context: “Yesterday I went to the mercado, comprei umas frutas, dan si, tai guela.”
- all 32 languages: “Yesterday I went to the mercado, comprei umas frutas, dan si, tai guela.”
