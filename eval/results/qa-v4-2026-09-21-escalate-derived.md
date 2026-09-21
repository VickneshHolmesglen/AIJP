# Answer-quality evaluation

- date: 2026-09-21
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 30 answerable + 8 unanswerable
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
| retrieval recall@1 | 50.0% |
| retrieval recall@3 | 80.0% |
| retrieval recall@5 | 90.0% |
| retrieval precision@5 (mean) | 28.0% |
| answered (not refused) | 90.0% (27/30, 95% CI 74-97%) |
| false refusals | 10.0% (3/30, 95% CI 3-26%) |
| correct overall (a refusal counts as wrong) | 76.7% (23/30, 95% CI 59-88%) |
| correct when answered | 85.2% (23/27, 95% CI 68-94%) |
| citation accuracy (a cited source is correct) | 100.0% (27/27, 95% CI 88-100%) |
| citation precision (mean share of cited sources that are correct) | 67.9% |

False-refusal reasons: model_declined = 3

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 75.0% (6/8, 95% CI 41-93%) | 25.0% (2/8, 95% CI 7-59%) |
| far (off-topic) | 66.7% (2/3, 95% CI 21-94%) | 33.3% (1/3, 95% CI 6-79%) |
| near (on-topic, fact absent) | 80.0% (4/5, 95% CI 38-96%) | 20.0% (1/5, 95% CI 4-62%) |

Refusal layer: insufficient_evidence = 1, model_declined = 5

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 29 of 29 answered |
| supported by their cited sources | 82.8% (24/29, 95% CI 65-92%) |
| **unsupported answer rate** | 17.2% (5/29, 95% CI 8-35%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `k02` (answerable): You get back 120 gold. The Frost Tower costs 80 gold (base cost). Upgrading to level 2 costs 0.75 × 80 × 2 = 120 gold in upgrades. Total invested = 80 + 120 = 200 gold. Selling refunds 60% of total invested: 0.6 × 200 = 120 gold.
- `k05` (answerable): Waves 2, 3, and 4 pay a total of 600 gold. Calculation: Base income is 100 gold per wave (Source [1], [3]). Income per wave number is 10 gold (Source [1], [3]). Flawless bonus is 25 gold per wave if no enemies leak (Source [1], [3]).
Wave 2: 100 + 10*2 + 25 = 145
Wave 3: 100 + 10*3 + 25 = 165
Wave 4: 100 + 10*4 + 25 = 185
Total: 145 + 165 + 185 = 495 gold.
- `k11` (answerable): A base Cannon shell deals 1.0 damage to a Shardlord after armor.
- `k16` (answerable): 40
- `y05` (near): Wave 11 spawns 8 grunts and 3 runners.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 1.3 s |
| p95 latency | 21.7 s |
| queries that called the LLM | 97.4% (37/38, 95% CI 87-100%) |
| answers re-checked with thinking | 13 of 29 answered (12 used, 1 fell back to the first answer) |
| mean prompt tokens per LLM call | 826 |
| mean completion tokens per LLM call | 312 |
| mean tokens per query (all queries) | 1108 |
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
| 0.55 | 100.0% | 12.5%  <- current default |
| 0.60 | 100.0% | 12.5% |
| 0.65 | 96.7% | 12.5% |
| 0.70 | 80.0% | 37.5% |
| 0.75 | 50.0% | 87.5% |
| 0.80 | 20.0% | 100.0% |

## Caveats

- 30 answerable + 8 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
