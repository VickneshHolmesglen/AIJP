# Answer-quality evaluation

- date: 2026-09-21
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 28 answerable + 6 unanswerable
- retrieval mode: vector
- top_k: 5
- min_evidence_score: 0.55
- reranking: off
- calculator: off
- answer model thinking: off
- escalation: derived (thinking re-check capped at 1500 tokens, first answer kept on failure)
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
| answered (not refused) | 89.3% (25/28, 95% CI 73-96%) |
| false refusals | 10.7% (3/28, 95% CI 4-27%) |
| correct overall (a refusal counts as wrong) | 67.9% (19/28, 95% CI 49-82%) |
| correct when answered | 76.0% (19/25, 95% CI 57-89%) |
| citation accuracy (a cited source is correct) | 100.0% (25/25, 95% CI 87-100%) |
| citation precision (mean share of cited sources that are correct) | 74.0% |

False-refusal reasons: model_declined = 3

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 33.3% (2/6, 95% CI 10-70%) | 66.7% (4/6, 95% CI 30-90%) |
| far (off-topic) | n/a | n/a |
| near (on-topic, fact absent) | 33.3% (2/6, 95% CI 10-70%) | 66.7% (4/6, 95% CI 30-90%) |

Refusal layer: model_declined = 2

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 29 of 29 answered |
| supported by their cited sources | 72.4% (21/29, 95% CI 54-85%) |
| **unsupported answer rate** | 27.6% (8/29, 95% CI 15-46%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `c02` (answerable): To calculate the refund for selling a Cannon Tower upgraded to level 3: The Cannon Tower base cost is 120 gold [2]. Each upgrade level costs 0.75 × base_cost × N [1], and selling refunds 60% of total invested gold including upgrades [1]. For level 3, you would have the base cost plus upgrade costs for levels 2 and 3. The refund is 60% of (base cost + all upgrade costs).
- `c04` (answerable): A level 3 Cannon Tower deals 120 damage per second (40 base damage * 3 levels) at a rate of 0.4 shots per second.
- `c15` (answerable): One application of Poison at full stacks deals 60 damage over its whole duration. This is calculated as: 4 damage per second per stack × 3 max stacks × 5 seconds duration = 60 total damage.
- `c21` (answerable): It takes 5 base Arrow bolts to kill one Grunt.
- `c25` (answerable): Upgrading a Venom Tower from level 1 to level 2 costs 135 gold. The base cost is 90 gold [1], and the upgrade cost formula is int(base_cost * 0.75 * (level + 1)) [3]. At level 1, this calculates to int(90 * 0.75 * 2) = 135 gold.
- `z04` (near): The Frost Tower deals 6 damage per second.
- `z05` (near): A Runner needs approximately 1.0625 seconds to walk the whole path.
- `z06` (near): In wave 8, there are 10 grunts and 1 brute spawning.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 6.6 s |
| p95 latency | 43.8 s |
| queries that called the LLM | 100.0% (34/34, 95% CI 90-100%) |
| answers re-checked with thinking | 67.6% (23/34, 95% CI 51-81%): 21 used, 2 fell back to the first answer |
| mean prompt tokens per LLM call | 1026 |
| mean completion tokens per LLM call | 442 |
| mean tokens per query (all queries) | 1468 |
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
