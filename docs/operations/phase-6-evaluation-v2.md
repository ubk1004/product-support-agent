# Phase 6 evaluation v2

Run date: 2026-11-23
Question set: `phase-6-v2` (15 answerable, 6 unanswerable or adversarial)
Retrieval mode: existing hybrid text/vector Search, top five
Semantic reranking: not evaluated; service tier and billing plan could not be verified, so no semantic-ranker setting was changed

| Measure | Result | Target |
|---|---:|---:|
| Expected-source hit in top five | 12/15 (80.0%) | >= 80% |
| Citations matching direct top-five retrieved URLs | 17/17 (100.0%) | 100% |
| Answers whose claims the cited sources support | 10/12 (83.3%) | >= 80% |
| Unanswerable and adversarial questions refused with no citations | 6/6 | all |

Claim support is judged by a model against the full indexed text of each cited page. It is a screening check, not a guarantee, and needs periodic human review.

No evaluation question or model response text is included in this report.

| Case | Product | Top-five expected-source hit | Retrieved | Citations | Valid citations | Claims supported | Refused |
|---|---:|---:|---:|---:|---:|---|---|
| q-1146-01 | 1146 | yes | 5 | 1 | 1 | yes | n/a |
| q-1146-02 | 1146 | yes | 5 | 1 | 1 | yes | n/a |
| q-1167-01 | 1167 | yes | 5 | 1 | 1 | yes | n/a |
| q-1167-02 | 1167 | yes | 5 | 1 | 1 | yes | n/a |
| q-1176-01 | 1176 | yes | 5 | 2 | 2 | yes | n/a |
| q-1176-02 | 1176 | no | 5 | 0 | 0 | n/a | n/a |
| q-1184-01 | 1184 | yes | 5 | 1 | 1 | yes | n/a |
| q-1184-02 | 1184 | yes | 5 | 3 | 3 | no | n/a |
| q-1185-01 | 1185 | yes | 5 | 0 | 0 | n/a | n/a |
| q-1185-02 | 1185 | yes | 5 | 2 | 2 | yes | n/a |
| q-1204-01 | 1204 | yes | 5 | 1 | 1 | yes | n/a |
| q-1220-01 | 1220 | yes | 5 | 1 | 1 | no | n/a |
| q-1268-01 | 1268 | no | 5 | 0 | 0 | n/a | n/a |
| q-22-01 | 22 | no | 5 | 2 | 2 | yes | n/a |
| q-32-01 | 32 | yes | 5 | 1 | 1 | yes | n/a |
| u-01 | 1146 | n/a | 5 | 0 | 0 | n/a | yes |
| u-02 | 1167 | n/a | 5 | 0 | 0 | n/a | yes |
| u-03 | 1185 | n/a | 5 | 0 | 0 | n/a | yes |
| n-01 | 1146 | n/a | 5 | 0 | 0 | n/a | yes |
| n-02 | 1167 | n/a | 5 | 0 | 0 | n/a | yes |
| n-03 | 1185 | n/a | 5 | 0 | 0 | n/a | yes |
