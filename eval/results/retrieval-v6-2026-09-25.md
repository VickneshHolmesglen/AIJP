# Retrieval benchmark

- date: 2026-09-25
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 32
- embedding model: nomic-embed-text
- embedding input: text only
- chunking: 1200 chars, 150 overlap
- hybrid: RRF k=60, pool=20 per retriever
- top_k: 10
- platform: Windows-10-10.0.19045-SP0

## Overall

| mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR@10 | mean latency (ms) |
|---|---|---|---|---|---|---|
| vector | 0.344 | 0.594 | 0.812 | 0.844 | 0.511 | 14 |
| lexical | 0.344 | 0.438 | 0.625 | 0.875 | 0.453 | 18 |
| hybrid | 0.344 | 0.594 | 0.750 | 0.812 | 0.493 | 26 |

Latency includes embedding the query (same cost in every mode).

## By question kind (recall@3 / MRR@10)

| kind | n | vector | lexical | hybrid |
|---|---|---|---|---|
| bridge_rule | 12 | 0.500 / 0.274 | 0.167 / 0.200 | 0.500 / 0.247 |
| bridge_data | 6 | 0.000 / 0.133 | 0.000 / 0.065 | 0.167 / 0.158 |
| bridge_code | 2 | 0.500 / 0.375 | 0.500 / 0.292 | 0.500 / 0.375 |
| lookup | 12 | 1.000 / 0.958 | 0.917 / 0.927 | 0.917 / 0.927 |

## Paired comparison against vector-only (by rank of first correct chunk)

| mode | better | worse | tied | sign-test p |
|---|---|---|---|---|
| lexical | 4 | 12 | 16 | 0.077 |
| hybrid | 3 | 5 | 24 | 0.727 |

## Questions where the modes disagree

| id | question | vector | lexical | hybrid |
|---|---|---|---|---|
| b01 | What does it cost to take a Frost Tower from level 2 to level 3? | 2 | 4 | 2 |
| b02 | What does one bolt from a level 2 Arrow Tower hit for? | miss | 7 | miss |
| b03 | How much damage does a level 3 Arrow Tower's bolt do to a Brute? | miss | 10 | miss |
| b05 | How much damage does a level 2 Cannon shell do to a Brute? | miss | 9 | miss |
| b06 | If a player ends a wave holding exactly the gold they started the run with, what interest do they receive? | 4 | 5 | 3 |
| b08 | What is the combined health of every enemy in wave 1? | 5 | miss | miss |
| b10 | What is the combined health of the flying enemies in wave 5? | 5 | miss | 5 |
| b12 | How many lives are lost if every enemy of wave 4 leaks? | 5 | 4 | 2 |
| b13 | How many lives does it cost if the whole of wave 3 gets through? | 5 | 7 | 4 |
| b14 | How much gold does filling every allowed tower spot with Arrow Towers cost? | 8 | 9 | 8 |
| b15 | Can a Cannon Tower be upgraded to level 4? | 2 | 5 | 3 |
| b16 | Can the Venom Tower's poison and the Cannon Tower's burn hurt the same enemy at the same time? | 4 | 10 | 4 |
| b17 | How much poison damage per second does a Shardlord with three poison stacks take? | 3 | 10 | 4 |
| b18 | How far does a chilled Brute walk in 10 seconds? | 2 | 4 | 3 |
| b20 | What does current_damage() return for a level 3 Venom Tower? | 2 | 3 | 2 |
| l09 | How many seconds pass between two enemy spawns? | 2 | 8 | 8 |

## Caveats

- 32 questions over a small synthetic corpus written by the project author. Treat differences of a few points as noise; the paired table shows how broad any gain is.
- Ranks are of the first *correct* chunk; a cell of `miss` means none in the top 10.
- Thresholds and reranking are not evaluated here.
