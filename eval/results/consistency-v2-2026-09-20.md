# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches_v2)
- claims: 22
- retrieval mode: vector
- passages per side: 4
- consistency_min_cosine: 0.6
- embedding model: nomic-embed-text
- judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0
- patched files: config/game.yaml, src/enemies/enemy.gd, src/towers/tower.gd

## Headline

| metric | value |
|---|---|
| seeded discrepancies found (recall) | 66.7% (4/6) |
| false alarms on consistent claims | 12.5% (1/8) |
| consistent claims confirmed | 87.5% (7/8) |
| unsupported claims left undecided | 87.5% (7/8) |
| unsupported claims given a verdict anyway | 12.5% (1/8) |
| verdicts citing a correct source on both sides | 85.7% (12/14) |
| overall verdict accuracy | 81.8% (18/22) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 4 | 2 | 0 |
| consistent | 1 | 7 | 0 |
| insufficient_evidence | 1 | 0 | 7 |

Downgrades: evidence_gate = 4

Tasks drafted (this runner never approves them): 6, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `z4` (seeded) expected potential_discrepancy, got consistent: Chill slows movement by 30 percent.
  - model: The design documentation [D1] and [D2] explicitly state that the Chill effect slows movement by 30 percent for 2 seconds. The implementation in [C4] configures 'chill_slow_ratio' as 0.3, and the physics logic in [C3] applies a multiplier of 0.6 (which corresponds to a 40% reduction or 60% speed remaining, effectively a 40% slow? Wait, let me re-read carefully). Actually, if speed *= 0.6, the new speed is 60% of the original, meaning it is slowed by 40%. However, looking at [C2], the formula uses (1.0 - chill_slow). If chill_slow is 0.3, the divisor is 0.7, resulting in a ~43% increase in time, which implies a ~30% speed reduction? No, if speed_new = speed_old * (1 - slow), then slow=0.3 means speed becomes 0.7 (30% slow). But [C3] hardcodes `speed *= 0.6`. This is a discrepancy. Let me re-evaluate the math. If I want to slow by 30%, the new speed should be 70% of the old speed (multiplier 0.7). The code in [C3] uses 0.6, which is a 40% slow. The config [C4] says 0.3. If the formula in [C2] is used with 0.3, it yields 0.7. But [C3] overrides this with 0.6. This is a potential discrepancy.
- `z6` (seeded) expected potential_discrepancy, got consistent: A boss enrages when its health drops below 25 percent.
  - model: The design document [D1] states that the Shardlord enrages when its health drops below 25 percent, and the configuration file [C2] confirms this with a setting of 'boss_enrage_health_ratio: 0.25', which corresponds to 25 percent.
- `y5` (consistent) expected consistent, got potential_discrepancy: Upgrading a tower to level N costs 0.75 times its base cost times N.
  - model: The design document [D1] states that upgrading to level N costs 0.75 times the base cost times N. However, the implementation in [C1] calculates the upgrade cost as `base_cost * 0.75 * (level + 1)`, which implies the cost is based on the target level rather than the current level increment, and also contradicts the design's implied incremental cost structure. Additionally, the maximum tower level defined in the code [C2] is 5, whereas the design limit [D3] suggests a max of 3.
- `x5` (unsupported) expected insufficient_evidence, got potential_discrepancy: Chill also reduces an enemy's armor.
  - model: The design documentation [D1] and [D4] states that the Chill effect only slows movement by 30 percent for 2 seconds, with no mention of armor reduction. The implementation code [C1] confirms this logic by setting a duration timer without modifying any armor property, while [C2] defines the slow ratio as 0.3 but does not include an armor reduction parameter. Therefore, the claim that Chill reduces armor contradicts both the design intent and the implemented behavior.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 2.4 s |
| p95 latency | 3.4 s |
| runs that consulted the model | 81.8% (18/22) |
| mean tokens per model call | 1104 |

## Evidence-gate calibration

Each side's best cosine must reach the threshold (a symbol found by name also counts for the implementation side). Here: the weaker of the two sides, for claims that HAVE evidence (seeded + consistent) versus claims that do not (unsupported).

| threshold | with-evidence let through | unsupported blocked |
|---|---|---|
| 0.30 | 100.0% | 0.0% |
| 0.35 | 100.0% | 0.0% |
| 0.40 | 100.0% | 0.0% |
| 0.45 | 100.0% | 0.0% |
| 0.50 | 100.0% | 12.5% |
| 0.55 | 100.0% | 25.0% |
| 0.60 | 100.0% | 50.0%  <- current default |
| 0.65 | 85.7% | 87.5% |
| 0.70 | 42.9% | 100.0% |
| 0.75 | 7.1% | 100.0% |
| 0.80 | 0.0% | 100.0% |

## Caveats

- 22 claims over a small synthetic corpus, written by the project author, who also chose where to seed the mismatches. Treat small differences as noise.
- Seeded mismatches are mostly changed numbers, which are easier to spot than subtle behavioural differences; only one (poison replacing instead of stacking) is behavioural.
- The same local model that judges here also answers questions elsewhere.
- A verdict is triage from retrieved passages, not proof of program behaviour.
