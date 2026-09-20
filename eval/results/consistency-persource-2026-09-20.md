# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches)
- claims: 16
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
| seeded discrepancies found (recall) | 83.3% (5/6) |
| false alarms on consistent claims | 0.0% (0/6) |
| consistent claims confirmed | 100.0% (6/6) |
| unsupported claims left undecided | 100.0% (4/4) |
| unsupported claims given a verdict anyway | 0.0% (0/4) |
| verdicts citing a correct source on both sides | 100.0% (12/12) |
| overall verdict accuracy | 93.8% (15/16) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 5 | 1 | 0 |
| consistent | 0 | 6 | 0 |
| insufficient_evidence | 0 | 0 | 4 |

Downgrades: evidence_gate = 4

Tasks drafted (this runner never approves them): 5, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `s1` (seeded) expected potential_discrepancy, got consistent: Poison stacks up to 3 times.
  - model: The claim that Poison stacks up to 3 times is supported by Design source [D1], which explicitly states 'It stacks up to 3 times'. This is further confirmed by Implementation sources [C2] and [C4], where the configuration file sets 'poison_max_stacks: 3' and the code defines 'const POISON_MAX_STACKS := 3'. Source [C1] supports this by initializing stacks to 1 upon application, allowing accumulation up to the defined maximum.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 3.6 s |
| p95 latency | 6.9 s |
| runs that consulted the model | 75.0% (12/16) |
| mean tokens per model call | 1284 |

## Evidence-gate calibration

Each side's best cosine must reach the threshold (a symbol found by name also counts for the implementation side). Here: the weaker of the two sides, for claims that HAVE evidence (seeded + consistent) versus claims that do not (unsupported).

| threshold | with-evidence let through | unsupported blocked |
|---|---|---|
| 0.30 | 100.0% | 0.0% |
| 0.35 | 100.0% | 0.0% |
| 0.40 | 100.0% | 0.0% |
| 0.45 | 100.0% | 0.0% |
| 0.50 | 100.0% | 25.0% |
| 0.55 | 100.0% | 50.0% |
| 0.60 | 100.0% | 100.0%  <- current default |
| 0.65 | 75.0% | 100.0% |
| 0.70 | 41.7% | 100.0% |
| 0.75 | 8.3% | 100.0% |
| 0.80 | 0.0% | 100.0% |

## Caveats

- 16 claims over a small synthetic corpus, written by the project author, who also chose where to seed the mismatches. Treat small differences as noise.
- Seeded mismatches are mostly changed numbers, which are easier to spot than subtle behavioural differences; only one (poison replacing instead of stacking) is behavioural.
- The same local model that judges here also answers questions elsewhere.
- A verdict is triage from retrieved passages, not proof of program behaviour.
