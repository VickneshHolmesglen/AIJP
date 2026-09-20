# Paired comparison of two QA runs

Pooled over 2 question set(s). 'gained' = right only in the second run, 'lost' = right only in the first. The sign test asks whether the gained/lost split could be luck.

| metric | n | first | second | gained | lost | sign-test p |
|---|---|---|---|---|---|---|
| answerable: correct (a refusal counts as wrong) | 64 | 40/64 (50-73%) | 26/64 (29-53%) | 0 | 14 | 0.000 |
| answerable: a cited source is correct | 64 | 56/64 (77-94%) | 38/64 (47-71%) | 2 | 20 | 0.000 |
| unanswerable: refused (correct behaviour) | 20 | 15/20 (53-89%) | 17/20 (64-95%) | 2 | 0 | 0.500 |
| near-miss unanswerable: refused | 16 | 11/16 (44-86%) | 13/16 (57-93%) | 2 | 0 | 0.500 |

Median latency per set (first -> second), seconds: 1.2 -> 2.0, 1.7 -> 2.3

Intervals are 95% Wilson. A p above 0.05 means the difference is within what luck produces at this sample size, which is not the same as showing there is no difference.
