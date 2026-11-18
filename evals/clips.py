"""The evaluation clips: what the learner says, and what we check in the transcript.

Each clip targets one failure mode from docs/evaluation-plan.md. `target` (and any `also`) is
what must appear in the transcript; `must_not` is a word that must NOT appear (for the deliberately
wrong attempt: the model shouldn't "auto-correct" the learner into the right word). `taught` is what
the tutor would have just taught before the learner's attempt; the key-terms run passes it to the
STT model as `keyterms_prompt`.
"""

CLIPS = [
    {
        "name": "question_biblioteca",
        "say": "How do I say biblioteca in a sentence?",
        "bucket": "Question with an embedded foreign word",
        "target": "biblioteca",
    },
    {
        "name": "question_el_perro",
        "say": "Why is it el perro and not la perro?",
        "bucket": "Question with an embedded foreign word",
        "target": "el perro",
    },
    {
        "name": "attempt_es_correct",
        "say": "¿Dónde está la biblioteca?",
        "bucket": "Learner attempt, correct",
        "target": "biblioteca",
        "taught": ["biblioteca"],
    },
    {
        "name": "attempt_es_wrong",
        "say": "¿Dónde está la bibliotica?   (say it wrong on purpose: bib-lio-TI-ca)",
        "bucket": "Learner attempt, incorrect (false acceptance)",
        "target": "bibliotica",
        "taught": ["biblioteca"],
        "must_not": "biblioteca",
    },
    {
        "name": "attempt_pt_correct",
        "say": "Eu preciso de um advogado.",
        "bucket": "Learner attempt, correct (the 'advocado' case)",
        "target": "advogado",
        "taught": ["advogado"],
    },
    {
        "name": "single_word_advogado",
        "say": "Advogado.",
        "bucket": "Single-word turn",
        "target": "advogado",
        "taught": ["advogado"],
    },
    {
        "name": "attempt_zh_correct",
        "say": "我想去图书馆。   (Wǒ xiǎng qù túshūguǎn)",
        "bucket": "Learner attempt, correct (Mandarin)",
        "target": "图书馆",
        "taught": ["图书馆"],
    },
    {
        "name": "hesitant",
        "say": "How do you say... um... the thing you pay at a restaurant... the bill?   (pause ~1 s at each '...')",
        "bucket": "Hesitant speech (premature end-of-turn)",
        "target": "bill",
        "single_turn": True,
    },
    {
        "name": "mixed_four_languages",
        "say": "Yesterday I went to the mercado, comprei umas frutas, 但是太贵了.",
        "bucket": "Code-switching, four languages",
        "target": "mercado",
        "also": ["comprei", "太贵"],  # Portuguese stays Portuguese; Mandarin comes out as Chinese
    },
]
