# Answer-quality evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 36 answerable + 14 unanswerable
- retrieval mode: vector
- top_k: 5
- min_evidence_score: 0.55
- reranking: off
- calculator: ON (the model writes arithmetic, code evaluates it)
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
| answered (not refused) | 94.4% (34/36, 95% CI 82-98%) |
| false refusals | 5.6% (2/36, 95% CI 2-18%) |
| correct overall (a refusal counts as wrong) | 63.9% (23/36, 95% CI 48-78%) |
| correct when answered | 67.6% (23/34, 95% CI 51-81%) |
| citation accuracy (a cited source is correct) | 94.1% (32/34, 95% CI 81-98%) |
| citation precision (mean share of cited sources that are correct) | 81.4% |

False-refusal reasons: insufficient_evidence = 2

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 92.9% (13/14, 95% CI 69-99%) | 7.1% (1/14, 95% CI 1-31%) |
| far (off-topic) | 100.0% (4/4, 95% CI 51-100%) | 0.0% (0/4, 95% CI 0-49%) |
| near (on-topic, fact absent) | 90.0% (9/10, 95% CI 60-98%) | 10.0% (1/10, 95% CI 2-40%) |

Refusal layer: insufficient_evidence = 1, model_declined = 12

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 35 of 35 answered |
| supported by their cited sources | 77.1% (27/35, 95% CI 61-88%) |
| **unsupported answer rate** | 22.9% (8/35, 95% CI 12-39%) |

Judge validated on 14 hand-labelled cases: accuracy 85.7% (12/14); approved an unfaithful answer 1x, rejected a faithful one 1x, unparseable 0x.

Answers the judge marked unsupported:

- `m01` (answerable): 180
- `m02` (answerable): 27
- `m03` (answerable): 190
- `m04` (answerable): 150
- `m06` (answerable): No, you cannot use Frost Towers against flying enemies because Wraiths are immune to Chill and only towers that can target the air can hurt them.
- `m08` (answerable): No. According to source [3], 'Chill does not stack; reapplying only refreshes the timer.' Since the enemy is already chilled, hitting it again with a shell (which applies Chill) will not add more slow but will refresh the duration, meaning the enemy remains slowed.
- `m11` (answerable): 125 gold
- `w14` (near): The upgrade discount factor is 0.75 (from source [2] and [3]). The cost to upgrade to level N is calculated as base_cost * 0.75 * N. For the Frost Tower, base_cost is 80 (source [1]). To reach level 3 from level 2, we calculate the cost for N=3: 80 * 0.75 * 3 = 180. The question asks for the 'discount', which implies the multiplier applied to the base cost per level step or the specific cost at that step. However, the phrasing 'upgrade discount at level 3' likely refers to the cost of the upgrade that takes the tower to level 3 (from level 2). Using the formula in [3]: cost = int(base_cost * 0.75 * (level + 1)). Here 'level' is the current level before upgrade. To go from 2 to 3, level=2. Cost = int(80 * 0.75 * (2+1)) = int(80 * 0.75 * 3) = int(180) = 180. The 'discount' is the factor 0.75 applied to the base cost scaled by the step number.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 1.4 s |
| p95 latency | 2.3 s |
| queries that called the LLM | 94.0% (47/50, 95% CI 84-98%) |
| mean prompt tokens per LLM call | 859 |
| mean completion tokens per LLM call | 48 |
| mean tokens per query (all queries) | 852 |
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
