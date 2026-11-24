---
description: "Security requirements for GitHub Actions workflows"
applyTo: ".github/workflows/**/*.{yml,yaml},.github/workflows/*.{yml,yaml}"
---

# GitHub Actions security

Follow `.github/copilot-instructions.md` and the pipeline description in `infra/README.md`. Keep build, infrastructure, and deployment workflows separate.

* Pin every external action to a verified full commit SHA, including first-party actions.
* Set explicit least-privilege permissions. Grant `id-token: write` only to jobs that need approved OIDC authentication.
* Treat pull request metadata, artifacts, and caches as untrusted. Do not interpolate untrusted values directly into shell scripts or run untrusted code in privileged workflows.
* Do not expose secrets to untrusted code. Disable checkout credential persistence when it is not required.
* Restrict deployment to manual `workflow_dispatch` runs from `main` with a protected GitHub environment. Jobs that reach the private registry run on self-hosted `<env>-vnet` runners.
* Validate workflows with the approved tooling and review triggers, runner trust, dependencies, permissions, and cloud identity boundaries.
