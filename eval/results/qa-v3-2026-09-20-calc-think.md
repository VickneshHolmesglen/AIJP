# Answer-quality evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 28 answerable + 6 unanswerable
- retrieval mode: vector
- top_k: 5
- min_evidence_score: 0.55
- reranking: off
- calculator: ON (the model writes arithmetic, code evaluates it)
- answer model thinking: ON (the judge never thinks)
- embedding model: nomic-embed-text
- answer + judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0

## Answerable questions

| metric | value |
|---|---|
| retrieval recall@1 | 28.6% |
| retrieval recall@3 | 82.1% |
| retrieval recall@5 | 85.7% |
| retrieval precision@5 (mean) | 32.9% |
| answered (not refused) | 75.0% (21/28, 95% CI 57-87%) |
| false refusals | 25.0% (7/28, 95% CI 13-43%) |
| correct overall (a refusal counts as wrong) | 64.3% (18/28, 95% CI 46-79%) |
| correct when answered | 85.7% (18/21, 95% CI 65-95%) |
| citation accuracy (a cited source is correct) | 100.0% (21/21, 95% CI 85-100%) |
| citation precision (mean share of cited sources that are correct) | 81.7% |

False-refusal reasons: calculation_failed = 3, model_declined = 4

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 66.7% (4/6, 95% CI 30-90%) | 33.3% (2/6, 95% CI 10-70%) |
| far (off-topic) | n/a | n/a |
| near (on-topic, fact absent) | 66.7% (4/6, 95% CI 30-90%) | 33.3% (2/6, 95% CI 10-70%) |

Refusal layer: model_declined = 4

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 23 of 23 answered |
| supported by their cited sources | 73.9% (17/23, 95% CI 54-87%) |
| **unsupported answer rate** | 26.1% (6/23, 95% CI 13-46%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `c02` (answerable): You get back 234 gold when selling a Cannon Tower upgraded to level 3.
- `c12` (answerable): It takes 7.2 seconds to spawn every enemy of wave 3, calculated as (10 enemies - 1) × 0.8 seconds spawn interval.
- `c15` (answerable): One application of Poison at full stacks (3 stacks) deals 60 damage over its whole duration, calculated as 4 damage per second per stack × 3 stacks × 5 seconds duration.
- `c16` (answerable): Burn deals 18 damage in total over its full duration.
- `c21` (answerable): It takes 5 base Arrow bolts to kill one Grunt.
- `c25` (answerable): Upgrading a Venom Tower from level 1 to level 2 costs 135 gold.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 7.9 s |
| p95 latency | 37.5 s |
| queries that called the LLM | 100.0% (34/34, 95% CI 90-100%) |
| mean prompt tokens per LLM call | 878 |
| mean completion tokens per LLM call | 730 |
| mean tokens per query (all queries) | 1608 |
| estimated cost per query | $0.0000 |

Token counts are as reported by Ollama. Cost = tokens x configured prices ($0.0/1M input, $0.0/1M output). The default of 0 reflects a local model: $0.0000 means 'free to run locally', not 'cheap in production'.

## Evidence-gate calibration

The gate alone: refuse when the best chunk cosine is below the threshold. Shows what each candidate threshold would let through / block, before the LLM's own judgement.

| threshold | answerable let through | unanswerable blocked |
|---|---|---|
| 0.30 | 100.0% | 0.0% |
| 0.35 | 100.0% | 0.0% |
| 0.40 | 100.0% | 0.0% |
| 0.45 | 100.0% | 0.0% |
| 0.50 | 100.0% | 0.0% |
| 0.55 | 100.0% | 0.0%  <- current default |
| 0.60 | 100.0% | 0.0% |
| 0.65 | 100.0% | 0.0% |
| 0.70 | 89.3% | 33.3% |
| 0.75 | 64.3% | 83.3% |
| 0.80 | 17.9% | 100.0% |

## Caveats

- 28 answerable + 6 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
