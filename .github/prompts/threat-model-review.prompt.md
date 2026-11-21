---
description: "Review threat and privacy requirements for an approved implementation phase"
argument-hint: "phase=..."
---

# Threat and privacy review

Read `docs/implementation-plan.md` and the approved architecture and decisions available in the workspace.

1. Identify assets, data flows, trust boundaries, assumptions, and missing evidence for the requested phase.
2. Apply STRIDE and the AI-specific threat scenarios listed in Phase 0b, including prompt injection, citation spoofing, exfiltration, SSRF, quota abuse, and sensitive telemetry.
3. For each applicable threat, record its rationale, mitigation, owner, verification, status, and corresponding cloud control. Distinguish planned controls from controls verified in code.
4. Identify privacy approval and retention gaps. Do not mark threats mitigated without evidence or substitute this review for accountable approval.
