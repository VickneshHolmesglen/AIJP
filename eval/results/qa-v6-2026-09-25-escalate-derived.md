# Answer-quality evaluation

- date: 2026-09-25
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 32 answerable + 8 unanswerable
- retrieval mode: vector
- top_k: 5
- min_evidence_score: 0.55
- reranking: off
- calculator: off
- answer model thinking: off
- answer token cap: 1024 (a cut-off answer is refused)
- escalation: derived (thinking re-check capped at 1500 tokens, first answer kept on failure)
- embedding model: nomic-embed-text
- embedding input: text only
- answer + judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0

## Answerable questions

| metric | value |
|---|---|
| retrieval recall@1 | 34.4% |
| retrieval recall@3 | 59.4% |
| retrieval recall@5 | 81.2% |
| retrieval precision@5 (mean) | 32.5% |
| answered (not refused) | 90.6% (29/32, 95% CI 76-97%) |
| false refusals | 9.4% (3/32, 95% CI 3-24%) |
| correct overall (a refusal counts as wrong) | 75.0% (24/32, 95% CI 58-87%) |
| correct when answered | 82.8% (24/29, 95% CI 65-92%) |
| citation accuracy (a cited source is correct) | 100.0% (29/29, 95% CI 88-100%) |
| citation precision (mean share of cited sources that are correct) | 84.7% |

False-refusal reasons: model_declined = 3

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 87.5% (7/8, 95% CI 53-98%) | 12.5% (1/8, 95% CI 2-47%) |
| far (off-topic) | 100.0% (1/1, 95% CI 21-100%) | 0.0% (0/1, 95% CI 0-79%) |
| near (on-topic, fact absent) | 85.7% (6/7, 95% CI 49-97%) | 14.3% (1/7, 95% CI 3-51%) |

Refusal layer: model_declined = 7

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 30 of 30 answered |
| supported by their cited sources | 73.3% (22/30, 95% CI 56-86%) |
| **unsupported answer rate** | 26.7% (8/30, 95% CI 14-44%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `b01` (answerable): It costs 60 gold.
- `b04` (answerable): An Arrow Tower costs 50 gold [2]. Upgrading once (to level 2) costs 0.75 × 50 × 2 = 75 gold according to source [1], making total investment 125 gold. Selling refunds 60% of total invested, so 0.6 × 125 = 75 gold comes back [1][5].
- `b06` (answerable): The player receives 10 gold in interest.
- `b11` (answerable): The combined health of all enemies in wave 4 is 600. Wave 4 contains 10 Grunts (60 health each) and 1 Brute (200 health). Total = (10 * 60) + 200 = 800.
- `b12` (answerable): If every enemy of wave 4 leaks, the player loses 10 lives. Wave 4 contains 10 grunts (each costing 1 life) and 1 brute (costing 5 lives). Total = (10 * 1) + (1 * 5) = 15 lives.
- `b18` (answerable): A chilled Brute walks 315 units in 10 seconds. The Brute has a base speed of 45 (source [2]), Chill slows movement by 30 percent (source [1]), so the chilled speed is 45 * 0.7 = 31.5. Distance = 31.5 * 10 = 315.
- `b19` (answerable): For a Cannon Tower that was never upgraded, sell_value() returns 72 gold. This is calculated as int(total_invested * SELL_REFUND_RATIO) where total_invested equals the base cost of 120 gold (from source [3]) and SELL_REFUND_RATIO is 0.6 (from source [2]).
- `l08` (answerable): 60

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 1.4 s |
| p95 latency | 13.3 s |
| queries that called the LLM | 100.0% (40/40, 95% CI 91-100%) |
| answers re-checked with thinking | 35.0% (14/40, 95% CI 22-50%): 12 used, 2 fell back to the first answer |
| mean prompt tokens per LLM call | 829 |
| mean completion tokens per LLM call | 208 |
| mean tokens per query (all queries) | 1037 |
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
| 0.65 | 93.8% | 25.0% |
| 0.70 | 75.0% | 37.5% |
| 0.75 | 43.8% | 87.5% |
| 0.80 | 12.5% | 100.0% |

## Caveats

- 32 answerable + 8 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
