# Retrieval benchmark

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 37
- embedding model: nomic-embed-text
- chunking: 1200 chars, 150 overlap
- hybrid: RRF k=60, pool=20 per retriever
- top_k: 10
- platform: Windows-10-10.0.19045-SP0

## Overall

| mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR@10 | mean latency (ms) |
|---|---|---|---|---|---|---|
| vector | 0.811 | 0.919 | 0.946 | 0.973 | 0.875 | 72 |
| lexical | 0.432 | 0.703 | 0.838 | 0.919 | 0.591 | 74 |
| hybrid | 0.595 | 0.892 | 0.973 | 1.000 | 0.749 | 123 |

Latency includes embedding the query (same cost in every mode).

## By question kind (recall@3 / MRR@10)

| kind | n | vector | lexical | hybrid |
|---|---|---|---|---|
| paraphrase | 10 | 1.000 / 0.900 | 0.400 / 0.347 | 0.800 / 0.567 |
| identifier | 10 | 1.000 / 0.950 | 0.900 / 0.708 | 1.000 / 0.867 |
| numeric | 9 | 1.000 / 1.000 | 1.000 / 0.870 | 1.000 / 1.000 |
| code_location | 8 | 0.625 / 0.612 | 0.500 / 0.435 | 0.750 / 0.546 |

## Paired comparison against vector-only (by rank of first correct chunk)

| mode | better | worse | tied |
|---|---|---|---|
| lexical | 4 | 18 | 15 |
| hybrid | 4 | 11 | 22 |

## Questions where the modes disagree

| id | question | vector | lexical | hybrid |
|---|---|---|---|---|
| p02 | Which defensive structure is the cheapest way to deal with ghosts that float over the path? | 1 | 10 | 3 |
| p04 | What happens if the final villain gets past my defences? | 2 | miss | 4 |
| p05 | Which enemy shrugs off cheap low-power turrets? | 1 | 6 | 1 |
| p06 | Do cold effects and fire effects work together on the same target? | 1 | miss | 3 |
| p07 | How much money do I get back when I demolish a defence? | 1 | 1 | 2 |
| p08 | How does the game persist player progress between sessions? | 1 | 5 | 2 |
| p09 | What do I earn for clearing a wave without letting anything through? | 1 | 2 | 1 |
| p10 | Which foe moves quickest but dies easily? | 1 | miss | 4 |
| i04 | What does GameState own? | 2 | 3 | 3 |
| i06 | What is EventBus used for? | 1 | 2 | 1 |
| i08 | What is HIT_EFFICIENCY? | 1 | 2 | 1 |
| i09 | What does the _enrage function do? | 1 | 2 | 1 |
| i10 | What is boss_leak_penalty? | 1 | 4 | 3 |
| n06 | What is the maximum number of towers allowed at once? | 1 | 3 | 1 |
| n08 | How much does it cost to upgrade a tower to level 3? | 1 | 2 | 1 |
| c01 | Where is damage reduced by armor calculated? | 2 | 1 | 1 |
| c02 | Where do waves get loaded from disk? | 1 | 5 | 2 |
| c03 | Which code decides when a wave is cleared? | 1 | 4 | 2 |
| c04 | How does a tower pick which enemy to shoot? | miss | 3 | 6 |
| c05 | Where is tower upgrading implemented? | 7 | 5 | 5 |
| c06 | Where is the poison effect applied to enemies? | 4 | 1 | 2 |
| c07 | What code simulates whether a defence can survive a wave? | 1 | 6 | 2 |
| c08 | Where is the enrage behaviour for bosses implemented? | 1 | 3 | 1 |

## Caveats

- 37 questions over a small synthetic corpus written by the project author. Treat differences of a few points as noise; the paired table shows how broad any gain is.
- Ranks are of the first *correct* chunk; a cell of `miss` means none in the top 10.
- Thresholds and reranking are not evaluated here.
