---
description: "Security requirements for future GitHub Actions workflows"
applyTo: ".github/workflows/**/*.{yml,yaml},.github/workflows/*.{yml,yaml}"
---

# GitHub Actions security

Follow the approval gates and workflow separation in `docs/implementation-plan.md`. Do not enable application deployment as part of the MVP.

* Pin every external action to a verified full commit SHA, including first-party actions.
* Set explicit least-privilege permissions. Grant `id-token: write` only to jobs that need approved OIDC authentication.
* Treat pull request metadata, artifacts, and caches as untrusted. Do not interpolate untrusted values directly into shell scripts or run untrusted code in privileged workflows.
* Do not expose secrets to untrusted code. Disable checkout credential persistence when it is not required.
* Restrict deployment to an approved manual workflow and protected environment. The full application deployment remains disabled.
* Validate workflows with the approved tooling and review triggers, runner trust, dependencies, permissions, and cloud identity boundaries.
