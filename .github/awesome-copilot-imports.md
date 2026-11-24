---
title: Awesome Copilot imports
description: Provenance and review notes for local Copilot customizations
---

## Source and license

The upstream assets below were retrieved from [github/awesome-copilot](https://github.com/github/awesome-copilot) at commit `f10fdb8b2660ce85c98f220b2f1ca24653768a5c`. The upstream MIT license and copyright notice are retained in [awesome-copilot-MIT.txt](./licenses/awesome-copilot-MIT.txt). These files have been adapted for this project.

| Local asset | Upstream path | Adaptation |
|---|---|---|
| [ADR Generator](./agents/adr-generator.agent.md) | `agents/adr-generator.agent.md` | Uses this project's ADR location and register |
| [Accessibility Expert](./agents/accessibility.agent.md) | `agents/accessibility.agent.md` | Adds Next.js chat UI scope and the WCAG 2.2 AA target; removes unpinned execution examples and fixed model/tools |
| [Azure AVM Bicep](./agents/azure-verified-modules-bicep.agent.md) | `agents/azure-verified-modules-bicep.agent.md` | Adds approval boundaries for Azure changes and removes environment-specific tool names |
| [Bicep guidance](./instructions/bicep-code-best-practices.instructions.md) | `instructions/bicep-code-best-practices.instructions.md` | Adds project infrastructure constraints and avoids indiscriminate API upgrades |
| [Microsoft Agent Framework skill](./skills/microsoft-agent-framework/SKILL.md) | `skills/microsoft-agent-framework/` | Adds local architecture and privacy constraints; avoids an unpinned install |

The local project instructions and prompts are project-specific additions, not upstream imports.

## Review boundaries

Candidates were inspected as text before installation. No upstream scripts, hooks, MCP configuration, executable workflow, or dependencies were installed or run. The review checked for unexpected execution, sensitive-data handling, external dependencies, conflicting deployment instructions, and compatibility with the project guidance. This is a static review, not a guarantee of safety; review future upstream updates before importing them.

Other candidates were excluded when their defaults conflicted with the project guidance or required substantial correction, including automatic Bicep upgrades, unrestricted evaluation-trajectory logging, overbroad workflow-security assumptions, and a 100% line-coverage mandate. The larger threat-model skill was not imported because its complete reference and orchestration package was not reviewed. The upstream workflow catalog did not contain a suitable project CI or deployment workflow. The project's own workflows are in `.github/workflows/`.
