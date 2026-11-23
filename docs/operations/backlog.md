---
title: Operations Backlog
description: Track outstanding repository governance and operational work
author: Udaybhanu Karmakar
ms.date: 2026-11-21
ms.topic: reference
---

## Repository branch protection

* ID: OPS-001
* Status: Pending, requires an authorized repository maintainer
* Priority: High, required before the Phase 1 merge-gate exit criterion is met
* Owner: Repository maintainer
* Scope: Protect the default branch of `ubk1004/product-support-agent`

Configure a GitHub branch protection rule or ruleset after reviewing the
repository's available controls and running the
[validation workflow](../../.github/workflows/validate.yml) on GitHub.
No repository settings have been changed. The active CLI account could not
access this repository on 2026-11-21, so this item is tracked locally rather
than as a GitHub issue. Do not switch shared credentials to complete it.

### Acceptance criteria

* Confirm the default branch and configure protection for it.
* Require pull requests and at least one approval, including code-owner review
  using [CODEOWNERS](../../.github/CODEOWNERS). Dismiss stale approvals and
  require review conversations to be resolved.
* Confirm the actual GitHub check names and require all validation jobs:
  `Python checks (3.11)`, `Python checks (3.13)`, `Web checks`, and
  `Secret scanning`. Require the branch to be up to date before merging.
* Block force pushes and branch deletion. Review administrator and ruleset
  bypass permissions; document any approved exception.
* Verify on a controlled test pull request that missing approval or a failing
  required check blocks merging, and that approved, passing changes can merge.
  Obtain approval before creating that test pull request or merging it.
* Record the rule or ruleset, verification evidence, and completion date here.

This item does not authorize cloud deployment or Phase 2 implementation.
