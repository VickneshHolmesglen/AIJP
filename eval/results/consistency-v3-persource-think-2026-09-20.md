# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches_v3)
- claims: 22
- retrieval mode: vector
- passages per side: 4
- consistency_min_cosine: 0.6
- judge mode: per_source
- judge thinking: ON
- embedding model: nomic-embed-text
- judge model: qwen3.5
- platform: Windows-10-10.0.19045-SP0
- patched files: config/game.yaml, src/enemies/enemy.gd, src/towers/tower.gd

## Headline

| metric | value |
|---|---|
| seeded discrepancies found (recall) | 66.7% (4/6) |
| false alarms on consistent claims | 0.0% (0/8) |
| consistent claims confirmed | 100.0% (8/8) |
| unsupported claims left undecided | 87.5% (7/8) |
| unsupported claims given a verdict anyway | 12.5% (1/8) |
| verdicts citing a correct source on both sides | 84.6% (11/13) |
| overall verdict accuracy | 86.4% (19/22) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 4 | 1 | 1 |
| consistent | 0 | 8 | 0 |
| insufficient_evidence | 1 | 0 | 7 |

Downgrades: evidence_gate = 6, no_decisive_stance = 2

Tasks drafted (this runner never approves them): 5, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `a1` (seeded) expected potential_discrepancy, got consistent: No hit ever deals less than 1 damage.
  - model: Design sources D1 and D2 explicitly state that hits are clamped to a minimum damage value, while implementation source C4 confirms this value is 1. Implementation source C1 mirrors this logic with `max(1.0, ...)`, supporting the claim directly. Although C2 uses a different armor calculation (`armor / 2`), it still enforces a minimum floor via `max(MIN_DAMAGE, ...)`, which supports the claim regarding the damage floor.
- `a4` (seeded) expected potential_discrepancy, got insufficient_evidence [evidence_gate]: The Arrow Tower fires at the closest enemy.
  - model: No sufficiently relevant implementation evidence was found for this claim.
- `d7` (unsupported) expected insufficient_evidence, got potential_discrepancy: Selling a tower during a wave gives a smaller refund.
  - model: Design source [D1] states that selling a tower refunds 60 percent of the total gold invested, implying a fixed rate rather than a reduced one during waves. Implementation source [C2] defines `SELL_REFUND_RATIO` as a constant 0.6, which contradicts the claim that the refund is smaller specifically during a wave. The other sources discuss economy mechanics or architecture unrelated to the specific selling refund condition.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 48.3 s |
| p95 latency | 98.3 s |
| runs that consulted the model | 72.7% (16/22) |
| mean tokens per model call | 5132 |

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
