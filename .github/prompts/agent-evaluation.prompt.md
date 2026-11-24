---
description: "Design or extend an evaluation for the product support agent"
argument-hint: "focus=..."
---

# Agent evaluation

Start from `tests/evaluation/questions-v2.json`, `scripts/run_evaluation.py`, and the decisions in `docs/architecture/decision-register.md`.

1. Define measurable cases for the requested focus, including expected evidence and source IDs where relevant.
2. Cover groundedness, citation validity, unsupported requests, injection and exfiltration resistance, latency, and cost as applicable.
3. Use synthetic or approved data, deterministic fakes for routine tests, and an isolated live environment only with explicit approval.
4. Report thresholds, missing approvals, limitations, and failing cases without retaining sensitive queries or responses.
