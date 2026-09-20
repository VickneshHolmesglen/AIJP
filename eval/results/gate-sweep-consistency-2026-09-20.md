# Consistency gate: pooled sweep

Pooled from: consistency-2026-09-20.json, consistency-v2-2026-09-20.json, consistency-v3-2026-09-20.json.

| threshold | claims with evidence let through | unsupported claims blocked |
|---|---|---|
| 0.30 | 100% (40/40; 91-100%) | 0% (0/20; 0-16%) |
| 0.35 | 100% (40/40; 91-100%) | 0% (0/20; 0-16%) |
| 0.40 | 100% (40/40; 91-100%) | 0% (0/20; 0-16%) |
| 0.45 | 100% (40/40; 91-100%) | 0% (0/20; 0-16%) |
| 0.50 | 100% (40/40; 91-100%) | 10% (2/20; 3-30%) |
| 0.55 | 100% (40/40; 91-100%) | 30% (6/20; 15-52%) |
| 0.60 | 98% (39/40; 87-100%) | 65% (13/20; 43-82%)  <- current default |
| 0.65 | 80% (32/40; 65-90%) | 90% (18/20; 70-97%) |
| 0.70 | 40% (16/40; 26-55%) | 100% (20/20; 84-100%) |
| 0.75 | 5% (2/40; 1-17%) | 100% (20/20; 84-100%) |
| 0.80 | 0% (0/40; 0-9%) | 100% (20/20; 84-100%) |

A higher threshold blocks more unsupported claims but starts losing real ones. The unsupported set is small and half of it is on-topic near-misses, which score high because they are about the right subject; a cosine gate cannot tell 'about the right subject' from 'contains the answer'. Read the intervals: with about a dozen unsupported claims a difference of one or two is noise.
