# Paired comparison of two QA runs

Pooled over 2 question set(s). 'gained' = right only in the second run, 'lost' = right only in the first. The sign test asks whether the gained/lost split could be luck.

| metric | n | first | second | gained | lost | sign-test p |
|---|---|---|---|---|---|---|
| answerable: correct (a refusal counts as wrong) | 72 | 59/72 (72-89%) | 59/72 (72-89%) | 2 | 2 | 1.000 |
| answerable: a cited source is correct | 72 | 64/72 (80-94%) | 64/72 (80-94%) | 1 | 1 | 1.000 |
| unanswerable: refused (correct behaviour) | 26 | 24/26 (76-98%) | 24/26 (76-98%) | 0 | 0 | 1.000 |
| near-miss unanswerable: refused | 16 | 14/16 (64-97%) | 14/16 (64-97%) | 0 | 0 | 1.000 |

Median latency per set (first -> second), seconds: 1.2 -> 2.9, 1.2 -> 3.0

Intervals are 95% Wilson. A p above 0.05 means the difference is within what luck produces at this sample size, which is not the same as showing there is no difference.
