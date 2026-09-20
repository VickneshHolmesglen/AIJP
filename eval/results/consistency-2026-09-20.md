# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches)
- claims: 16
- retrieval mode: vector
- passages per side: 4
- consistency_min_cosine: 0.55
- embedding model: nomic-embed-text
- judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0
- patched files: config/game.yaml, src/enemies/enemy.gd, src/towers/tower.gd

## Headline

| metric | value |
|---|---|
| seeded discrepancies found (recall) | 66.7% (4/6) |
| false alarms on consistent claims | 0.0% (0/6) |
| consistent claims confirmed | 100.0% (6/6) |
| unsupported claims left undecided | 75.0% (3/4) |
| unsupported claims given a verdict anyway | 25.0% (1/4) |
| verdicts citing a correct source on both sides | 100.0% (12/12) |
| overall verdict accuracy | 81.2% (13/16) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 4 | 2 | 0 |
| consistent | 0 | 6 | 0 |
| insufficient_evidence | 1 | 0 | 3 |

Downgrades: evidence_gate = 2

Tasks drafted (this runner never approves them): 5, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `s1` (seeded) expected potential_discrepancy, got consistent: Poison stacks up to 3 times.
  - model: The design documentation [D1] states that Poison stacks up to 3 times, and the implementation in [C4] defines a constant POISON_MAX_STACKS set to 3. Additionally, the configuration file [C2] explicitly sets poison_max_stacks to 3, confirming the claim.
- `s3` (seeded) expected potential_discrepancy, got consistent: When a boss enrages it gains 50 percent more movement speed.
  - model: The design document [D1] states that when the Shardlord's health drops below 25 percent, it enrages and gains 50 percent more movement speed. The implementation in [C1] confirms this behavior by multiplying the current move_speed by 1.25 (which represents a 25% increase) upon entering the enraged state, aligning with the design specification.
- `u3` (unsupported) expected insufficient_evidence, got potential_discrepancy: The Venom Tower fires two shots per second.
  - model: The design documentation [D1] describes the Venom Tower's value as coming from damage over time via Poison, while the implementation configuration [C2] confirms a poison duration of 5 seconds and max stacks of 3. However, neither source explicitly states the Venom Tower's fire rate; instead, the claim asserts it fires two shots per second, which contradicts the design implication that its primary mechanic is DoT rather than rapid projectile firing like the Arrow Tower [D2]. Without a specific fire rate value in the provided implementation or design sources for the Venom Tower, we cannot confirm if it actually fires two shots per second as claimed.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 29.1 s |
| p95 latency | 41.3 s |
| runs that consulted the model | 87.5% (14/16) |
| mean tokens per model call | 1102 |

## Evidence-gate calibration

Each side's best cosine must reach the threshold (a symbol found by name also counts for the implementation side). Here: the weaker of the two sides, for claims that HAVE evidence (seeded + consistent) versus claims that do not (unsupported).

| threshold | with-evidence let through | unsupported blocked |
|---|---|---|
| 0.30 | 100.0% | 0.0% |
| 0.35 | 100.0% | 0.0% |
| 0.40 | 100.0% | 0.0% |
| 0.45 | 100.0% | 0.0% |
| 0.50 | 100.0% | 25.0% |
| 0.55 | 100.0% | 50.0%  <- current default |
| 0.60 | 100.0% | 100.0% |
| 0.65 | 75.0% | 100.0% |
| 0.70 | 41.7% | 100.0% |
| 0.75 | 8.3% | 100.0% |
| 0.80 | 0.0% | 100.0% |

## Caveats

- 16 claims over a small synthetic corpus, written by the project author, who also chose where to seed the mismatches. Treat small differences as noise.
- Seeded mismatches are mostly changed numbers, which are easier to spot than subtle behavioural differences; only one (poison replacing instead of stacking) is behavioural.
- The same local model that judges here also answers questions elsewhere.
- A verdict is triage from retrieved passages, not proof of program behaviour.
