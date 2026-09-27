# Evaluation

How this project knows whether it works, and what it tried that did not. Every number here is copied
from a report the evaluation tooling wrote into [`eval/results/`](../eval/results/); nothing is typed
in by hand. The UI's **Evaluation** page renders the same files.

## The benchmark

A small synthetic software project, *Shardfall*, a Godot tower-defence game
([`eval/corpus/`](../eval/corpus/)): design documents, GDScript and Python source, a YAML config and
a JSON data file. 11 files, 73 chunks. Question sets are JSON files in
[`eval/datasets/`](../eval/datasets/) with the exact chunks each answer needs, so retrieval and
answers are scored separately.

| Runner | Measures |
|---|---|
| `python -m eval.retrieval` | recall@k and MRR@10 for vector, lexical and hybrid search |
| `python -m eval.qa` | correct answers, citation accuracy, refusals (off-topic and near-miss), faithfulness (LLM judge, itself validated on hand-labelled cases), latency, tokens |
| `python -m eval.consistency` | the design-vs-code check against deliberately seeded mismatches |
| `python -m eval.compare A.json B.json` | paired comparison of two runs: gained/lost questions, Wilson 95% intervals, sign test |

## Headline results (v1 set, current defaults)

| | Result | Report |
|---|---|---|
| Correct answers | 33/36 (95% CI 78-97%) | `qa-2026-09-27-escalate-derived.md` |
| A cited source is correct | 34/36 | same |
| False refusals | 0/36 | same |
| Unanswerable questions refused | 11/12 (6/6 off-topic, 5/6 near-miss) | same |
| Median latency (local GPU) | 1.1 s | same |
| Retrieval, vector | recall@5 0.946, MRR@10 0.875 | `retrieval-2026-09-20.md` |
| Design vs code: seeded mismatches found | 4/6, with 0/6 false alarms and 4/4 unsupported claims left undecided | `consistency-2026-09-20.md` |

## How experiments are run

The first question set was written early, so later ideas were tested on **new question sets written
and committed to git before the feature existed** (v3 to v7). Each variant runs once, every arm is
reported, and a change becomes a default only when a paired comparison supports it. Question sets
that inspired a feature are "dev" sets and are never used to report its result.

## What helped

- **Capped thinking for computed numbers (on by default).** Answer without thinking first; only if
  the answer contains a number that is not in the cited passages, re-ask with a thinking pass capped
  at 1500 tokens and 45 s. Pooled over 94 held-out questions: 57 -> 69 correct, 12 gained and 0 lost
  (`compare-escalation-2026-09-21.md`). Plain lookups cost nothing extra.
- **A token cap on every answer (on by default).** One question made the model reason inside its
  JSON answer for 15,665 tokens, failing the request after 3 minutes. Now it is refused as
  `answer_truncated` in about 15 s, and a cut-off answer that happens to parse is never shown.

## What did not help (and is off or was removed)

- **LLM reranker.** Ranks the right chunk first more often (vector MRR@10 0.875 -> 0.911) but answers
  did not improve (34/36 -> 33/36) and latency more than doubled (`rerank-2026-09-20.md`,
  `qa-2026-09-20-rerank.md`). The answer model already sees 5 chunks and recall@5 is 0.946.
- **Server-side calculator.** The model was asked to write arithmetic for the server to evaluate.
  On a held-out set it went from 15/28 to 5/28 correct: the model wrote wrong formulas and often did
  not delegate at all (`qa-v3-2026-09-20-calc.md`).
- **Embedding each chunk with its file and heading path.** On a held-out set of multi-source
  questions, answers fell from 24/32 to 17/32 (p=0.039,
  `compare-sectionpath-v6-2026-09-25.md`): file names echo the question words (`enemy.gd`,
  `wave_spawner.gd`), so the prefix lifted many wrong chunks at once.
- **A second retrieval hop, data-file restructuring, MMR diversity and a larger k** were each tried
  on the development sets only and were neutral or worse, so none was built and the held-out v7
  set was left unused. The reason is consistent: questions that combine a named thing with a
  general rule or data table need 2-4 chunks, the rule chunks never name the thing, and a 5-chunk
  budget over a 73-chunk corpus cannot reliably hold all of them.

## Honest limits

- The question sets are small and were written by the AI assistant that built the system, not an
  independent party. Differences of a few questions are noise; every proportion carries an interval.
- The faithfulness judge is the same local model that answers; it scored 12/12 on easy validation
  cases but 12/14 on harder ones.
- Latencies are from one machine with a local GPU and are only comparable within the same day and
  machine state (a game or a browser holding GPU memory can cut generation speed by 4-7x).
