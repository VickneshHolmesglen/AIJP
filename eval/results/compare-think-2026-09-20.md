# Paired comparison of two QA runs

Pooled over 2 question set(s). 'gained' = right only in the second run, 'lost' = right only in the first. The sign test asks whether the gained/lost split could be luck.

| metric | n | first | second | gained | lost | sign-test p |
|---|---|---|---|---|---|---|
| answerable: correct (a refusal counts as wrong) | 64 | 40/64 (50-73%) | 46/64 (60-81%) | 7 | 1 | 0.070 |
| answerable: a cited source is correct | 64 | 56/64 (77-94%) | 53/64 (72-90%) | 0 | 3 | 0.250 |
| unanswerable: refused (correct behaviour) | 20 | 15/20 (53-89%) | 19/20 (76-99%) | 4 | 0 | 0.125 |
| near-miss unanswerable: refused | 16 | 11/16 (44-86%) | 15/16 (72-99%) | 4 | 0 | 0.125 |

Median latency per set (first -> second), seconds: 1.2 -> 7.5, 1.7 -> 9.9

Intervals are 95% Wilson. A p above 0.05 means the difference is within what luck produces at this sample size, which is not the same as showing there is no difference.
