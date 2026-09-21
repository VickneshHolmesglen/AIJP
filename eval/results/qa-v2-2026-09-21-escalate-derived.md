# Answer-quality evaluation

- date: 2026-09-21
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 36 answerable + 14 unanswerable
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
| retrieval recall@1 | 33.3% |
| retrieval recall@3 | 72.2% |
| retrieval recall@5 | 91.7% |
| retrieval precision@5 (mean) | 25.6% |
| answered (not refused) | 91.7% (33/36, 95% CI 78-97%) |
| false refusals | 8.3% (3/36, 95% CI 3-22%) |
| correct overall (a refusal counts as wrong) | 75.0% (27/36, 95% CI 59-86%) |
| correct when answered | 81.8% (27/33, 95% CI 66-91%) |
| citation accuracy (a cited source is correct) | 90.9% (30/33, 95% CI 76-97%) |
| citation precision (mean share of cited sources that are correct) | 79.8% |

False-refusal reasons: insufficient_evidence = 2, model_declined = 1

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
| answers judged | 34 of 34 answered |
| supported by their cited sources | 79.4% (27/34, 95% CI 63-90%) |
| **unsupported answer rate** | 20.6% (7/34, 95% CI 10-37%) |

Judge validated on 14 hand-labelled cases: accuracy 85.7% (12/14); approved an unfaithful answer 1x, rejected a faithful one 1x, unparseable 0x.

Answers the judge marked unsupported:

- `m01` (answerable): Upgrading a Cannon Tower to level 2 costs 180 gold.
- `m02` (answerable): A fully upgraded Arrow Tower deals 48 damage per shot.
- `m06` (answerable): No, you cannot effectively use Frost Towers against flying enemies because Wraiths are immune to the Chill effect applied by Frost Tower ice shards [3], and only towers that can target the air can hurt them [3].
- `m08` (answerable): Yes. According to source [3], the Chill status effect slows movement by 30 percent for 2 seconds and does not stack; reapplying it only refreshes the timer. Therefore, if a chilled enemy is hit again (e.g., by a Cannon shell), they remain slowed until the 2-second duration expires or is refreshed.
- `h01` (answerable): The Shardlord (boss) is worth the most loot with a bounty of 25 gold, as stated in source [4]. The Brute has a bounty of 25 gold [2], while the Grunt and default Enemy have bounties of 5 gold [3, 5].
- `h05` (answerable): The file data/waves.json specifies the number of monsters (enemies) for each wave.
- `w14` (near): The Frost Tower's upgrade discount is 25% (using a 0.75 multiplier). According to source [2], 'Upgrading to level N costs 0.75 times the base cost times N.' Source [3] confirms this with the formula `int(base_cost * 0.75 * (level + 1))`. The Frost Tower's base cost is 80 gold per source [1].

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 1.3 s |
| p95 latency | 22.3 s |
| queries that called the LLM | 94.0% (47/50, 95% CI 84-98%) |
| answers re-checked with thinking | 16.0% (8/50, 95% CI 8-29%): 6 used, 2 fell back to the first answer |
| mean prompt tokens per LLM call | 713 |
| mean completion tokens per LLM call | 152 |
| mean tokens per query (all queries) | 814 |
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
