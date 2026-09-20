# Answer-quality evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 36 answerable + 14 unanswerable
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
| retrieval recall@1 | 33.3% |
| retrieval recall@3 | 72.2% |
| retrieval recall@5 | 91.7% |
| retrieval precision@5 (mean) | 25.6% |
| answered (not refused) | 86.1% (31/36, 95% CI 71-94%) |
| false refusals | 13.9% (5/36, 95% CI 6-29%) |
| correct overall (a refusal counts as wrong) | 72.2% (26/36, 95% CI 56-84%) |
| correct when answered | 83.9% (26/31, 95% CI 67-93%) |
| citation accuracy (a cited source is correct) | 93.5% (29/31, 95% CI 79-98%) |
| citation precision (mean share of cited sources that are correct) | 81.7% |

False-refusal reasons: calculation_failed = 1, insufficient_evidence = 2, model_declined = 1, ungrounded_number = 1

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 78.6% (11/14, 95% CI 52-92%) | 21.4% (3/14, 95% CI 8-48%) |
| far (off-topic) | 75.0% (3/4, 95% CI 30-95%) | 25.0% (1/4, 95% CI 5-70%) |
| near (on-topic, fact absent) | 80.0% (8/10, 95% CI 49-94%) | 20.0% (2/10, 95% CI 6-51%) |

Refusal layer: insufficient_evidence = 1, model_declined = 9, ungrounded_number = 1

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 34 of 34 answered |
| supported by their cited sources | 85.3% (29/34, 95% CI 70-94%) |
| **unsupported answer rate** | 14.7% (5/34, 95% CI 6-30%) |

Judge validated on 14 hand-labelled cases: accuracy 85.7% (12/14); approved an unfaithful answer 1x, rejected a faithful one 1x, unparseable 0x.

Answers the judge marked unsupported:

- `m01` (answerable): Upgrading a Cannon Tower to level 2 costs 180 gold.
- `m04` (answerable): If you sell a level 3 Arrow Tower, you get back 97.5 gold.
- `m06` (answerable): No, you cannot effectively use Frost Towers against flying enemies because Wraiths (flying enemies) are immune to Chill, and the Frost Tower's primary effect is applying the Chill effect. Only towers that can target the air can hurt flying enemies, but since flying enemies are immune to Chill, the Frost Tower would be ineffective.
- `h05` (answerable): The file data/waves.json says how many monsters come in each round.
- `w12` (near): The interest rate does not change after wave 30; it remains at a fixed 5 percent (0.05) according to the economy configuration.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 7.4 s |
| p95 latency | 31.5 s |
| queries that called the LLM | 94.0% (47/50, 95% CI 84-98%) |
| mean prompt tokens per LLM call | 877 |
| mean completion tokens per LLM call | 501 |
| mean tokens per query (all queries) | 1295 |
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
| 0.50 | 100.0% | 7.1% |
| 0.55 | 94.4% | 7.1%  <- current default |
| 0.60 | 88.9% | 14.3% |
| 0.65 | 66.7% | 28.6% |
| 0.70 | 55.6% | 57.1% |
| 0.75 | 22.2% | 85.7% |
| 0.80 | 2.8% | 100.0% |

## Caveats

- 36 answerable + 14 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
