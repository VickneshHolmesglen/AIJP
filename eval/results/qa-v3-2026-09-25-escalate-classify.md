# Answer-quality evaluation

- date: 2026-09-25
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 28 answerable + 6 unanswerable
- retrieval mode: vector
- top_k: 5
- min_evidence_score: 0.55
- reranking: off
- calculator: off
- answer model thinking: off
- escalation: classify (thinking re-check capped at 1500 tokens, first answer kept on failure)
- embedding model: nomic-embed-text
- answer + judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0

**1 question(s) errored and are excluded:** c02

## Answerable questions

| metric | value |
|---|---|
| retrieval recall@1 | 29.6% |
| retrieval recall@3 | 81.5% |
| retrieval recall@5 | 85.2% |
| retrieval precision@5 (mean) | 32.6% |
| answered (not refused) | 88.9% (24/27, 95% CI 72-96%) |
| false refusals | 11.1% (3/27, 95% CI 4-28%) |
| correct overall (a refusal counts as wrong) | 70.4% (19/27, 95% CI 52-84%) |
| correct when answered | 79.2% (19/24, 95% CI 60-91%) |
| citation accuracy (a cited source is correct) | 100.0% (24/24, 95% CI 86-100%) |
| citation precision (mean share of cited sources that are correct) | 74.3% |

False-refusal reasons: model_declined = 3

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 50.0% (3/6, 95% CI 19-81%) | 50.0% (3/6, 95% CI 19-81%) |
| far (off-topic) | n/a | n/a |
| near (on-topic, fact absent) | 50.0% (3/6, 95% CI 19-81%) | 50.0% (3/6, 95% CI 19-81%) |

Refusal layer: model_declined = 3

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 27 of 27 answered |
| supported by their cited sources | 85.2% (23/27, 95% CI 68-94%) |
| **unsupported answer rate** | 14.8% (4/27, 95% CI 6-32%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `c10` (answerable): Wave 5 pays a total bounty of 107 gold. This consists of 4 Wraiths (value not explicitly defined in sources) and 8 Grunts (5 gold each). However, based strictly on the provided sources, only the Grunt bounty is defined as 5 gold [3]. The source for Wave 5 composition [5] lists 4 'wraith' and 8 'grunt'. Without a defined bounty for 'wraith', the total cannot be fully calculated from the given text. If we assume only known bounties apply or if 'wraith' has no bounty, the answer is 40 gold (8 grunts * 5). But typically in such questions, missing data implies unanswerable or requires assumption. Given the strict rule 'If the sources do not contain the answer', and 'wraith' bounty is missing, the answer is technically uncalculable.
- `c25` (answerable): Upgrading a Venom Tower from level 1 to level 2 costs 135 gold. This is calculated using the base cost of 90 gold (from [1]) and the upgrade formula int(base_cost * 0.75 * (level + 1)) where level=1, giving int(90 * 0.75 * 2) = 135 (from [3]).
- `z05` (near): A Runner needs approximately 1.0625 seconds to walk the whole path.
- `z06` (near): In wave 8, there are 10 grunts and 1 brute spawning.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 7.7 s |
| p95 latency | 22.3 s |
| queries that called the LLM | 100.0% (33/33, 95% CI 90-100%) |
| answers re-checked with thinking | 78.8% (26/33, 95% CI 62-89%): 22 used, 4 fell back to the first answer |
| mean prompt tokens per LLM call | 1103 |
| mean completion tokens per LLM call | 433 |
| mean tokens per query (all queries) | 1536 |
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
| 0.70 | 88.9% | 33.3% |
| 0.75 | 63.0% | 83.3% |
| 0.80 | 18.5% | 100.0% |

## Caveats

- 27 answerable + 6 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
