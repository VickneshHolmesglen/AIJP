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
- embedding input: file + heading path + text
- answer + judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0

## Answerable questions

| metric | value |
|---|---|
| retrieval recall@1 | 34.4% |
| retrieval recall@3 | 59.4% |
| retrieval recall@5 | 65.6% |
| retrieval precision@5 (mean) | 27.5% |
| answered (not refused) | 75.0% (24/32, 95% CI 58-87%) |
| false refusals | 25.0% (8/32, 95% CI 13-42%) |
| correct overall (a refusal counts as wrong) | 53.1% (17/32, 95% CI 36-69%) |
| correct when answered | 70.8% (17/24, 95% CI 51-85%) |
| citation accuracy (a cited source is correct) | 95.8% (23/24, 95% CI 80-99%) |
| citation precision (mean share of cited sources that are correct) | 83.0% |

False-refusal reasons: model_declined = 8

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
| answers judged | 25 of 25 answered |
| supported by their cited sources | 68.0% (17/25, 95% CI 48-83%) |
| **unsupported answer rate** | 32.0% (8/25, 95% CI 17-52%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `b01` (answerable): It costs 60 gold.
- `b03` (answerable): A level 3 Arrow Tower's bolt deals 18 damage to a Brute (calculated as int(12 * (1.0 + 0.25 * (3 - 1))) = 18). Note: The Brute has 8 armor which subtracts from incoming hits, but the exact reduction mechanics are not specified in the sources.
- `b06` (answerable): The player receives 10 gold in interest.
- `b13` (answerable): 5 lives
- `b18` (answerable): A chilled Brute walks 300 pixels in 10 seconds.
- `b19` (answerable): sell_value() returns 72 for a Cannon Tower that was never upgraded. This is calculated as int(total_invested * SELL_REFUND_RATIO) where total_invested = 120 (Cannon Tower base cost from [4]) and SELL_REFUND_RATIO = 0.6 (from [3]), giving int(120 * 0.6) = 72.
- `l08` (answerable): 60
- `u03` (near): Wave 6 pays a total bounty of 725 gold (100 base + 50 for wave number + 25 flawless bonus).

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 1.3 s |
| p95 latency | 14.6 s |
| queries that called the LLM | 100.0% (40/40, 95% CI 91-100%) |
| answers re-checked with thinking | 22.5% (9/40, 95% CI 12-38%): 8 used, 1 fell back to the first answer |
| mean prompt tokens per LLM call | 743 |
| mean completion tokens per LLM call | 175 |
| mean tokens per query (all queries) | 918 |
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
| 0.65 | 87.5% | 37.5% |
| 0.70 | 62.5% | 87.5% |
| 0.75 | 37.5% | 100.0% |
| 0.80 | 6.2% | 100.0% |

## Caveats

- 32 answerable + 8 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
