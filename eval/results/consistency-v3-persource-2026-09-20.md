# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches_v3)
- claims: 22
- retrieval mode: vector
- passages per side: 4
- consistency_min_cosine: 0.6
- judge mode: per_source
- judge thinking: off
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
| unsupported claims left undecided | 87.5% (7/8) |
| unsupported claims given a verdict anyway | 12.5% (1/8) |
| verdicts citing a correct source on both sides | 92.3% (12/13) |
| overall verdict accuracy | 90.9% (20/22) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 5 | 0 | 1 |
| consistent | 0 | 8 | 0 |
| insufficient_evidence | 0 | 1 | 7 |

Downgrades: evidence_gate = 6, no_decisive_stance = 2

Tasks drafted (this runner never approves them): 5, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `a4` (seeded) expected potential_discrepancy, got insufficient_evidence [evidence_gate]: The Arrow Tower fires at the closest enemy.
  - model: No sufficiently relevant implementation evidence was found for this claim.
- `d7` (unsupported) expected insufficient_evidence, got consistent: Selling a tower during a wave gives a smaller refund.
  - model: The claim states that selling a tower gives a smaller refund, which aligns with the design documentation [D1] specifying a 60% refund rate and the implementation constant [C2] setting SELL_REFUND_RATIO to 0.6. Since the refund is explicitly defined as a fixed percentage (60%) rather than a dynamic value that decreases based on timing or other factors, the evidence supports the claim by confirming the existence of a specific, non-full refund mechanism.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 3.2 s |
| p95 latency | 5.8 s |
| runs that consulted the model | 72.7% (16/22) |
| mean tokens per model call | 1272 |

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
