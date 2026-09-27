# Answer-quality evaluation

- date: 2026-09-27
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 36 answerable + 12 unanswerable
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
- llm api: OpenAI-compatible chat completions at http://127.0.0.1:11434/v1
- platform: Windows-10-10.0.19045-SP0

## Answerable questions

| metric | value |
|---|---|
| retrieval recall@1 | 83.3% |
| retrieval recall@3 | 94.4% |
| retrieval recall@5 | 97.2% |
| retrieval precision@5 (mean) | 27.8% |
| answered (not refused) | 100.0% (36/36, 95% CI 90-100%) |
| false refusals | 0.0% (0/36, 95% CI 0-10%) |
| correct overall (a refusal counts as wrong) | 91.7% (33/36, 95% CI 78-97%) |
| correct when answered | 91.7% (33/36, 95% CI 78-97%) |
| citation accuracy (a cited source is correct) | 94.4% (34/36, 95% CI 82-98%) |
| citation precision (mean share of cited sources that are correct) | 82.9% |

False-refusal reasons: none

## Unanswerable questions (correct behaviour = refuse)

| set | refused | answered anyway |
|---|---|---|
| all | 91.7% (11/12, 95% CI 65-99%) | 8.3% (1/12, 95% CI 1-35%) |
| far (off-topic) | 100.0% (6/6, 95% CI 61-100%) | 0.0% (0/6, 95% CI 0-39%) |
| near (on-topic, fact absent) | 83.3% (5/6, 95% CI 44-97%) | 16.7% (1/6, 95% CI 3-56%) |

Refusal layer: insufficient_evidence = 3, model_declined = 8

## Faithfulness (LLM judge)

| metric | value |
|---|---|
| answers judged | 37 of 37 answered |
| supported by their cited sources | 89.2% (33/37, 95% CI 75-96%) |
| **unsupported answer rate** | 10.8% (4/37, 95% CI 4-25%) |

Judge validated on 12 hand-labelled cases: accuracy 100.0% (12/12); approved an unfaithful answer 0x, rejected a faithful one 0x, unparseable 0x.

Answers the judge marked unsupported:

- `p04` (answerable): If the final villain (the Shardlord) gets past your defences and reaches the core, it is considered a leak. Since the Shardlord is a boss, leaking it costs 5 lives instead of the standard 1 life [2][5].
- `i03` (answerable): SELL_REFUND_RATIO is defined in src/towers/tower.gd (value 0.6) and config/game.yaml (value 0.6).
- `c08` (answerable): The enrage behavior for bosses is implemented in the `_enrage()` function in src/enemies/enemy.gd (source [1]), which is called from `take_damage()` when health drops below 25% of max_health and the enemy is a boss (source [3]). The function sets `_enraged = true`, increases move_speed by 1.5x, and emits the `enraged` signal.
- `u11` (near): Chill lasts for 2 seconds against bosses.

## Latency, tokens, cost

| metric | value |
|---|---|
| median latency (retrieval + generation) | 1.1 s |
| p95 latency | 6.2 s |
| queries that called the LLM | 93.8% (45/48, 95% CI 83-98%) |
| answers re-checked with thinking | 6.2% (3/48, 95% CI 2-17%): 3 used, 0 fell back to the first answer |
| mean prompt tokens per LLM call | 676 |
| mean completion tokens per LLM call | 87 |
| mean tokens per query (all queries) | 715 |
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
| 0.55 | 100.0% | 25.0%  <- current default |
| 0.60 | 91.7% | 33.3% |
| 0.65 | 75.0% | 41.7% |
| 0.70 | 63.9% | 66.7% |
| 0.75 | 41.7% | 91.7% |
| 0.80 | 8.3% | 100.0% |

## Caveats

- 36 answerable + 12 unanswerable questions over a small synthetic corpus written by the project author; treat small differences as noise.
- Correctness is a keyword check (required facts present), not a judgement of prose.
- Faithfulness is judged by the same local model that answers; see the judge validation.
- Generation uses temperature 0, but local inference is not guaranteed bit-identical.
