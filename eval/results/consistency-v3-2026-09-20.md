# Design-vs-code consistency evaluation

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus + eval/seeded_patches_v3)
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
| false alarms on consistent claims | 0.0% (0/8) |
| consistent claims confirmed | 100.0% (8/8) |
| unsupported claims left undecided | 62.5% (5/8) |
| unsupported claims given a verdict anyway | 37.5% (3/8) |
| verdicts citing a correct source on both sides | 92.3% (12/13) |
| overall verdict accuracy | 77.3% (17/22) |

## Confusion matrix (rows: expected, columns: got)

| expected \ got | potential_discrepancy | consistent | insufficient_evidence |
|---|---|---|---|
| potential_discrepancy | 4 | 1 | 1 |
| consistent | 0 | 8 | 0 |
| insufficient_evidence | 3 | 0 | 5 |

Downgrades: evidence_gate = 6

Tasks drafted (this runner never approves them): 7, one per discrepancy that survived validation.

## Where the check disagreed with the label

- `a2` (seeded) expected potential_discrepancy, got consistent: Applying Poison again refreshes its duration to 5 seconds.
  - model: The design document [D1] states that applying Poison refreshes the duration to 5 seconds, and the configuration file [C2] confirms this with 'poison_duration_sec: 5'. The implementation in [C1] sets 'poison_time_left = 8.0', which appears to be a discrepancy in the specific value (8 vs 5), but since the claim specifically asks about the *refresh* behavior and the config explicitly defines the duration as 5, the design intent is supported by the configuration while the code might use a different internal timing logic or unit. However, looking closer at [C1], it sets 8.0 seconds directly, which contradicts the design's 5 seconds stated in [D1] and [C2]. Wait, let me re-read carefully. The claim is 'Applying Poison again refreshes its duration to 5 seconds'. Design [D1] says exactly that. Config [C2] says 'poison_duration_sec: 5'. Code [C1] sets 'poison_time_left = 8.0'. This is a clear numerical discrepancy between the design/config (5s) and implementation (8s). Therefore, it is a potential_discrepancy.
- `a4` (seeded) expected potential_discrepancy, got insufficient_evidence [evidence_gate]: The Arrow Tower fires at the closest enemy.
  - model: No sufficiently relevant implementation evidence was found for this claim.
- `d4` (unsupported) expected insufficient_evidence, got potential_discrepancy: The enemy path is randomised at the start of every run.
  - model: The design documentation [D1] states that enemies walk along a 'fixed path' from the spawn gate to the Shard Core, which contradicts the claim that the path is randomised. While the implementation sources [C2] and [C3] show how waves are spawned and configured, they do not provide evidence of path randomization logic; instead, the design explicitly describes a fixed route.
- `d5` (unsupported) expected insufficient_evidence, got potential_discrepancy: Burn stops Poison from ticking.
  - model: The design documentation [D1] explicitly states that 'Poison and Burn can be active on the same enemy at the same time,' whereas the claim asserts that Burn stops Poison from ticking. The implementation code [C3] calculates poison damage based on stacks and time without any conditional check for the presence of a Burn status, further supporting the design's assertion that they coexist.
- `d7` (unsupported) expected insufficient_evidence, got potential_discrepancy: Selling a tower during a wave gives a smaller refund.
  - model: The design documentation [D1] explicitly states that selling a tower refunds 60 percent of the total gold invested, including upgrades. However, the implementation in [C2] defines `SELL_REFUND_RATIO` as 0.6 but does not specify any conditional logic or wave-state checks that would reduce this refund during an active wave. Without code showing a dynamic reduction based on wave status, the claim that refunds are smaller during waves appears unsupported by the provided sources.

## Latency and tokens

| metric | value |
|---|---|
| median latency | 2.4 s |
| p95 latency | 5.3 s |
| runs that consulted the model | 72.7% (16/22) |
| mean tokens per model call | 1130 |

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
