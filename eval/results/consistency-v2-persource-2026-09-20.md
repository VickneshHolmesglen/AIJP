# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches_v2)
- claims: 22
- retrieval mode: vector
- passages per side: 4
- consistency_min_cosine: 0.6
- judge mode: per_source
- embedding model: nomic-embed-text
- judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0
- patched files: config/game.yaml, src/enemies/enemy.gd, src/towers/tower.gd

## Headline

| metric | value |
|---|---|
| seeded discrepancies found (recall) | 66.7% (4/6) |
| false alarms on consistent claims | 12.5% (1/8) |
| consistent claims confirmed | 75.0% (6/8) |
| unsupported claims left undecided | 100.0% (8/8) |
| unsupported claims given a verdict anyway | 0.0% (0/8) |
| verdicts citing a correct source on both sides | 92.3% (12/13) |
| overall verdict accuracy | 81.8% (18/22) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 4 | 2 | 0 |
| consistent | 1 | 6 | 1 |
| insufficient_evidence | 0 | 0 | 8 |

Downgrades: evidence_gate = 4, no_decisive_stance = 5

Tasks drafted (this runner never approves them): 5, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `z4` (seeded) expected potential_discrepancy, got consistent: Chill slows movement by 30 percent.
  - model: Design sources [D1] and [D2] explicitly state that Chill slows movement by 30 percent, while implementation source [C4] confirms this with the configuration value 'chill_slow_ratio: 0.3'. The code in [C3] applies a multiplier of 0.6 to speed (which corresponds to a 40% reduction or 60% remaining speed), but since the claim specifies 'slows movement by 30 percent' (implying 70% speed remains) and the config defines the ratio as 0.3, the implementation logic aligns with the documented intent of a 30% slow factor defined in [C4]. Source [C1] supports this by setting a duration for the effect.
- `z6` (seeded) expected potential_discrepancy, got consistent: A boss enrages when its health drops below 25 percent.
  - model: Design source [D1] states that the Shardlord enrages when its health drops below 25 percent. Implementation source [C2] supports this with a configuration value of 0.25 for boss_enrage_health_ratio, which corresponds to 25 percent. The other sources are unrelated to the specific claim about the enrage threshold.
- `y1` (consistent) expected consistent, got insufficient_evidence [no_decisive_stance]: Arrow Towers can attack flying enemies such as Wraiths.
  - model: Design source [D1] states that 'Arrow bolts can hit flying enemies', directly supporting the claim. Design source [D2] describes Wraiths as flying but does not mention Arrow Towers specifically, making it unrelated to the specific interaction claimed. Implementation sources [C1], [C2], [C3], and [C4] deal with simulation logic, constants, initialization, and global limits respectively, none of which contain information about targeting capabilities or enemy types.
- `y5` (consistent) expected consistent, got potential_discrepancy: Upgrading a tower to level N costs 0.75 times its base cost times N.
  - model: Design source [D1] states that upgrading to level N costs 0.75 times the base cost times N. However, implementation source [C1] calculates the cost as `base_cost * 0.75 * (level + 1)`, which differs from the design formula by adding 1 to the level before multiplication. Source [C3] is unrelated as it only defines the maximum tower limit.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 3.7 s |
| p95 latency | 6.2 s |
| runs that consulted the model | 81.8% (18/22) |
| mean tokens per model call | 1270 |

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
