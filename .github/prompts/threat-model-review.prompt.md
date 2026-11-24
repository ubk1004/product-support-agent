---
description: "Review threat and privacy requirements for a change or component"
argument-hint: "scope=..."
---

# Threat and privacy review

Read `docs/architecture/architecture-overview.md`, `docs/security/threat-register.md`, and `docs/security/privacy-impact-assessment.md`.

1. Identify assets, data flows, trust boundaries, assumptions, and missing evidence for the requested scope.
2. Apply STRIDE and the AI-specific threat scenarios in the threat register, including prompt injection, citation spoofing, exfiltration, SSRF, quota abuse, and sensitive telemetry.
3. For each applicable threat, record its rationale, mitigation, owner, verification, status, and corresponding cloud control. Distinguish planned controls from controls verified in code.
4. Identify privacy approval and retention gaps. Do not mark threats mitigated without evidence or substitute this review for accountable approval.
