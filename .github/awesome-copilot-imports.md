---
title: Awesome Copilot imports
description: Provenance and review notes for local Copilot customizations
---

## Source and license

The upstream assets below were retrieved from [github/awesome-copilot](https://github.com/github/awesome-copilot) at commit `f10fdb8b2660ce85c98f220b2f1ca24653768a5c`. The upstream MIT license and copyright notice are retained in [awesome-copilot-MIT.txt](./licenses/awesome-copilot-MIT.txt). These files have been adapted for this project.

| Local asset | Upstream path | Adaptation |
|---|---|---|
| [ADR Generator](./agents/adr-generator.agent.md) | `agents/adr-generator.agent.md` | Uses the planned ADR location and review gates |
| [Accessibility Expert](./agents/accessibility.agent.md) | `agents/accessibility.agent.md` | Adds Chainlit scope; removes unpinned execution examples and fixed model/tools |
| [Azure AVM Bicep](./agents/azure-verified-modules-bicep.agent.md) | `agents/azure-verified-modules-bicep.agent.md` | Adds cloud approval boundaries and removes environment-specific tool names |
| [Bicep guidance](./instructions/bicep-code-best-practices.instructions.md) | `instructions/bicep-code-best-practices.instructions.md` | Adds Phase 7 constraints and avoids indiscriminate API upgrades |
| [Microsoft Agent Framework skill](./skills/microsoft-agent-framework/SKILL.md) | `skills/microsoft-agent-framework/` | Adds local architecture and privacy constraints; avoids an unpinned install |

The local project instructions and prompts are project-specific additions, not upstream imports.

## Review boundaries

Candidates were inspected as text before installation. No upstream scripts, hooks, MCP configuration, executable workflow, or dependencies were installed or run. The review checked for unexpected execution, sensitive-data handling, external dependencies, conflicting deployment instructions, and plan compatibility. This is a static review, not a guarantee of safety; review future upstream updates before importing them.

Other candidates were excluded when their defaults conflicted with the plan or required substantial correction, including automatic Bicep upgrades, unrestricted evaluation-trajectory logging, overbroad workflow-security assumptions, and a 100% line-coverage mandate. The larger threat-model skill was not imported because its complete reference and orchestration package was not reviewed. The upstream workflow catalog did not contain a suitable project CI or deployment workflow. The plan schedules those workflows for later approved phases, so this import does not enable them.
