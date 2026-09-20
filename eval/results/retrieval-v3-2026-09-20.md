# Retrieval benchmark

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 28
- embedding model: nomic-embed-text
- chunking: 1200 chars, 150 overlap
- hybrid: RRF k=60, pool=20 per retriever
- top_k: 10
- platform: Windows-10-10.0.19045-SP0

## Overall

| mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR@10 | mean latency (ms) |
|---|---|---|---|---|---|---|
| vector | 0.286 | 0.821 | 0.857 | 0.893 | 0.539 | 17 |
| lexical | 0.071 | 0.536 | 0.750 | 0.929 | 0.351 | 23 |
| hybrid | 0.321 | 0.679 | 0.857 | 0.893 | 0.518 | 33 |

Latency includes embedding the query (same cost in every mode).

## By question kind (recall@3 / MRR@10)

| kind | n | vector | lexical | hybrid |
|---|---|---|---|---|
| computation | 28 | 0.821 / 0.539 | 0.536 / 0.351 | 0.679 / 0.518 |

## Paired comparison against vector-only (by rank of first correct chunk)

| mode | better | worse | tied | sign-test p |
|---|---|---|---|---|
| lexical | 3 | 17 | 8 | 0.003 |
| hybrid | 2 | 8 | 18 | 0.109 |

## Questions where the modes disagree

| id | question | vector | lexical | hybrid |
|---|---|---|---|---|
| c01 | How much gold does a Cannon Tower cost in total when it is built and upgraded to level 3? | 2 | 5 | 2 |
| c02 | How much gold do I get back if I sell a Cannon Tower that was upgraded to level 3? | 2 | 5 | 3 |
| c03 | How much damage does a level 3 Cannon Tower deal per shell? | miss | 6 | 8 |
| c06 | How much gold does clearing wave 9 pay if no enemy leaks? | 1 | 2 | 1 |
| c07 | How much gold do waves 4 and 5 pay in total if both are cleared without leaks? | 1 | 2 | 1 |
| c08 | How much interest does a player earn at the start of a wave holding 600 unspent gold? | 1 | 2 | 1 |
| c09 | How much interest does a player earn at the start of a wave holding 2000 unspent gold? | 1 | 2 | 1 |
| c10 | How much bounty in total does wave 5 pay if every enemy in it is killed? | 6 | miss | miss |
| c11 | How many enemies spawn in total across waves 1, 2 and 3? | 1 | 3 | 1 |
| c12 | How many seconds does it take to spawn every enemy of wave 3, given the spawn interval? | 2 | 10 | 5 |
| c13 | How many lives are lost if three Grunts and a Shardlord leak? | 2 | 1 | 1 |
| c14 | A player starts with full lives. How many remain after a Shardlord and four other enemies leak? | 4 | 5 | 4 |
| c15 | How much poison damage can one application deal over its whole duration at full stacks? | 1 | 3 | 1 |
| c17 | How much damage does a base Cannon shell deal to a Brute after armor? | 3 | 7 | 4 |
| c18 | How much damage does one base Arrow bolt deal to a Brute after armor? | 3 | 7 | 4 |
| c22 | What is a Runner's speed while it is chilled? | 2 | 4 | 3 |
| c23 | At what health does the Shardlord enrage? | 1 | 2 | 1 |
| c24 | What is the combined health of one Grunt, one Runner and one Brute? | 3 | 4 | 4 |
| c25 | How much gold does upgrading a Venom Tower from level 1 to level 2 cost? | 2 | 5 | 3 |
| c28 | How much damage does a level 3 Frost Tower deal per shot? | miss | 7 | miss |

## Caveats

- 28 questions over a small synthetic corpus written by the project author. Treat differences of a few points as noise; the paired table shows how broad any gain is.
- Ranks are of the first *correct* chunk; a cell of `miss` means none in the top 10.
- Thresholds and reranking are not evaluated here.
