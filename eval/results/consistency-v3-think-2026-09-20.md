# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches_v3)
- claims: 22
- retrieval mode: vector
- passages per side: 4
- consistency_min_cosine: 0.6
- judge mode: verdict
- judge thinking: ON
- embedding model: nomic-embed-text
- judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0
- patched files: config/game.yaml, src/enemies/enemy.gd, src/towers/tower.gd

## Headline

| metric | value |
|---|---|
| seeded discrepancies found (recall) | 83.3% (5/6) |
| false alarms on consistent claims | 0.0% (0/8) |
| consistent claims confirmed | 100.0% (8/8) |
| unsupported claims left undecided | 62.5% (5/8) |
| unsupported claims given a verdict anyway | 37.5% (3/8) |
| verdicts citing a correct source on both sides | 84.6% (11/13) |
| overall verdict accuracy | 81.8% (18/22) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 5 | 0 | 1 |
| consistent | 0 | 8 | 0 |
| insufficient_evidence | 3 | 0 | 5 |

Downgrades: evidence_gate = 6

Tasks drafted (this runner never approves them): 8, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `a4` (seeded) expected potential_discrepancy, got insufficient_evidence [evidence_gate]: The Arrow Tower fires at the closest enemy.
  - model: No sufficiently relevant implementation evidence was found for this claim.
- `d4` (unsupported) expected insufficient_evidence, got potential_discrepancy: The enemy path is randomised at the start of every run.
  - model: Design documentation [D1] explicitly states that enemies walk along a "fixed path", which directly contradicts the claim that the path is randomised. The implementation sources provided, such as [C2], handle wave spawning but do not contain logic for generating randomized paths, aligning with the fixed path description in [D1].
- `d5` (unsupported) expected insufficient_evidence, got potential_discrepancy: Burn stops Poison from ticking.
  - model: Design source [D1] explicitly states that Poison and Burn can be active on the same enemy at the same time, which contradicts the claim. Furthermore, implementation source [C3] calculates poison damage in the _process function without checking for a conflicting Burn status effect, indicating they coexist in the code.
- `d7` (unsupported) expected insufficient_evidence, got potential_discrepancy: Selling a tower during a wave gives a smaller refund.
  - model: Design source [D1] states that selling a tower refunds a flat 60 percent of total gold invested, and implementation source [C2] defines SELL_REFUND_RATIO as a constant 0.6. Neither source indicates that the refund percentage decreases specifically when selling during a wave, which contradicts the claim.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 21.0 s |
| p95 latency | 42.1 s |
| runs that consulted the model | 72.7% (16/22) |
| mean tokens per model call | 2890 |

## Evidence-gate calibration

Each side's best cosine must reach the threshold (a symbol found by name also counts for the implementation side). Here: the weaker of the two sides, for claims that HAVE evidence (seeded + consistent) versus claims that do not (unsupported).

| threshold | with-evidence let through | unsupported blocked |
|---|---|---|
| 0.30 | 100.0% | 0.0% |
| 0.35 | 100.0% | 0.0% |
| 0.40 | 100.0% | 0.0% |
| 0.45 | 100.0% | 0.0% |
| 0.50 | 100.0% | 0.0% |
| 0.55 | 100.0% | 25.0% |
| 0.60 | 92.9% | 62.5%  <- current default |
| 0.65 | 78.6% | 87.5% |
| 0.70 | 35.7% | 100.0% |
| 0.75 | 0.0% | 100.0% |
| 0.80 | 0.0% | 100.0% |

## Caveats

- 22 claims over a small synthetic corpus, written by the project author, who also chose where to seed the mismatches. Treat small differences as noise.
- Seeded mismatches are mostly changed numbers, which are easier to spot than subtle behavioural differences; only one (poison replacing instead of stacking) is behavioural.
- The same local model that judges here also answers questions elsewhere.
- A verdict is triage from retrieved passages, not proof of program behaviour.
