# Retrieval benchmark

- date: 2026-09-20
- corpus: 11 files, 73 chunks (eval/corpus)
- questions: 36
- embedding model: nomic-embed-text
- chunking: 1200 chars, 150 overlap
- hybrid: RRF k=60, pool=20 per retriever
- top_k: 10
- platform: Windows-10-10.0.19045-SP0

## Overall

| mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR@10 | mean latency (ms) |
|---|---|---|---|---|---|---|
| vector | 0.333 | 0.722 | 0.917 | 1.000 | 0.562 | 42 |
| lexical | 0.167 | 0.583 | 0.694 | 0.806 | 0.382 | 19 |
| hybrid | 0.306 | 0.750 | 0.806 | 1.000 | 0.541 | 26 |

Latency includes embedding the query (same cost in every mode).

## By question kind (recall@3 / MRR@10)

| kind | n | vector | lexical | hybrid |
|---|---|---|---|---|
| multi_hop | 11 | 0.727 / 0.475 | 0.545 / 0.286 | 0.727 / 0.472 |
| negation | 5 | 1.000 / 0.767 | 1.000 / 0.633 | 1.000 / 0.700 |
| paraphrase_hard | 8 | 0.625 / 0.550 | 0.375 / 0.312 | 0.500 / 0.440 |
| code_reasoning | 7 | 0.429 / 0.325 | 0.286 / 0.324 | 0.714 / 0.492 |
| identifier | 5 | 1.000 / 0.900 | 1.000 / 0.533 | 1.000 / 0.767 |

## Paired comparison against vector-only (by rank of first correct chunk)

| mode | better | worse | tied | sign-test p |
|---|---|---|---|---|
| lexical | 7 | 21 | 8 | 0.013 |
| hybrid | 9 | 13 | 14 | 0.523 |

## Questions where the modes disagree

| id | question | vector | lexical | hybrid |
|---|---|---|---|---|
| m01 | How much gold does upgrading a Cannon Tower to level 2 cost? | 2 | 5 | 3 |
| m02 | How much damage does a fully upgraded Arrow Tower deal per shot? | 5 | 2 | 2 |
| m03 | What is the total gold needed to build a Frost Tower and upgrade it all the way to level 3? | 2 | 3 | 2 |
| m04 | If I sell a level 3 Arrow Tower, how much gold do I get back? | 2 | 3 | 2 |
| m05 | Which tower is the best answer to the boss, and why? | 3 | 7 | 4 |
| m06 | Can I use Frost Towers against the flying enemies? | 3 | 10 | 6 |
| m07 | Will burning enemies take extra damage from my cheapest tower? | 2 | 5 | 3 |
| m08 | After a Cannon shell hits a chilled enemy, is that enemy still slowed? | 9 | miss | 9 |
| m09 | How much gold do the two cheapest tower types cost together? | 4 | 2 | 2 |
| m10 | How much gold do waves 1 through 3 pay out in total if none leaks? | 1 | 3 | 1 |
| m11 | What does clearing wave 7 without a leak pay? | 1 | 2 | 1 |
| t01 | Which towers cannot target flying enemies? | 3 | 3 | 2 |
| t02 | Does Chill stack when it is applied repeatedly? | 1 | 3 | 2 |
| h01 | Which unit is worth the most loot when it dies? | 6 | miss | 10 |
| h02 | What ends a run? | 2 | 1 | 1 |
| h03 | How quickly does the game let me start the next round? | 5 | 2 | 6 |
| h04 | How frequently do individual monsters appear during a round? | 5 | miss | 6 |
| h05 | Which file says how many monsters come in each round? | 1 | miss | 2 |
| h07 | What can I buy with my opening funds? | 3 | miss | 3 |
| h08 | How does landing a killing blow turn into money? | 1 | miss | 4 |
| r01 | What happens to an enemy's poison stacks when the poison timer runs out? | 4 | 4 | 3 |
| r02 | What value does a tower's total_invested start with? | 5 | miss | 9 |
| r03 | What does upgrade() return when the tower is already at its maximum level? | 2 | 1 | 1 |
| r04 | How does the code recognise that an enemy is a boss? | 2 | 8 | 2 |
| r05 | By how much does the code multiply an enemy's speed while it is chilled? | 5 | 2 | 3 |
| r06 | What does WaveSpawner do once the last enemy of a wave is gone? | 8 | 7 | 6 |
| r07 | How does the offline simulator work out the towers' combined damage output? | 2 | 4 | 1 |
| d02 | What is boss_enrage_health_ratio set to? | 1 | 3 | 1 |
| d03 | What is max_tower_level? | 1 | 3 | 2 |
| d04 | What is chill_slow_ratio? | 1 | 2 | 1 |
| d05 | What is poison_duration_sec? | 2 | 2 | 3 |

## Caveats

- 36 questions over a small synthetic corpus written by the project author. Treat differences of a few points as noise; the paired table shows how broad any gain is.
- Ranks are of the first *correct* chunk; a cell of `miss` means none in the top 10.
- Thresholds and reranking are not evaluated here.
