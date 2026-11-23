---
title: Phase 6 Evaluation v1
description: Evaluation results for the local product support demo
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - evaluation
  - product support
  - retrieval
---

Run date: 2026-11-22
Question set: `phase-6-v1` (15 answerable, 3 unanswerable)
Retrieval mode: existing hybrid text/vector Search, top five
Semantic reranking: not evaluated; service tier and billing plan could not be verified, so no semantic-ranker setting was changed

| Measure | Result | Target |
|---|---:|---:|
| Expected-source hit in top five | 12/15 (80.0%) | >= 80% |
| Citations matching direct top-five retrieved URLs | 28/28 (100.0%) | 100% |
| Unanswerable questions refused with no citations | 3/3 | 3/3 |

No evaluation question or model response text is included in this report.

## Miss analysis and tuning

The final misses were `q-1176-02`, `q-1268-01`, and `q-22-01`. The likely cause
is a mismatch between query wording and the indexed source titles or terminology,
which left the expected source outside the top five. A title-aligned query
rewrite did not improve the misses. The second and final tuning iteration
expanded the vector candidate pool to four times the requested count and
recovered one expected source, raising the hit rate from 11/15 to 12/15. This
small synthetic set does not establish a definitive cause for the remaining
misses.

| Case | Product | Top-five expected-source hit | Retrieved | Citations | Valid citations | Refused |
|---|---:|---:|---:|---:|---:|---|
| q-1146-01 | 1146 | yes | 5 | 1 | 1 | n/a |
| q-1146-02 | 1146 | yes | 5 | 1 | 1 | n/a |
| q-1167-01 | 1167 | yes | 5 | 1 | 1 | n/a |
| q-1167-02 | 1167 | yes | 5 | 1 | 1 | n/a |
| q-1176-01 | 1176 | yes | 5 | 2 | 2 | n/a |
| q-1176-02 | 1176 | no | 5 | 2 | 2 | n/a |
| q-1184-01 | 1184 | yes | 5 | 2 | 2 | n/a |
| q-1184-02 | 1184 | yes | 5 | 4 | 4 | n/a |
| q-1185-01 | 1185 | yes | 5 | 2 | 2 | n/a |
| q-1185-02 | 1185 | yes | 5 | 4 | 4 | n/a |
| q-1204-01 | 1204 | yes | 5 | 1 | 1 | n/a |
| q-1220-01 | 1220 | yes | 5 | 1 | 1 | n/a |
| q-1268-01 | 1268 | no | 5 | 0 | 0 | n/a |
| q-22-01 | 22 | no | 5 | 5 | 5 | n/a |
| q-32-01 | 32 | yes | 5 | 1 | 1 | n/a |
| u-01 | 1146 | n/a | 5 | 0 | 0 | yes |
| u-02 | 1167 | n/a | 5 | 0 | 0 | yes |
| u-03 | 1185 | n/a | 5 | 0 | 0 | yes |
