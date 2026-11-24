---
description: "Python reference for the Microsoft Agent Framework skill"
---

# Microsoft Agent Framework for Python

Use this reference when the target project is written in Python.

## Authoritative sources

- Repository: <https://github.com/microsoft/agent-framework/tree/main/python>
- Samples: <https://github.com/microsoft/agent-framework/tree/main/python/samples>

## Installation

Verify the current Python package and release status in official documentation before changing the version. The project pins its version in `pyproject.toml` and `uv.lock`; change it through `uv`.

## Python-specific guidance

- Use modern async patterns throughout agent and workflow operations.
- Add type hints and keep APIs explicit even in dynamic code.
- Follow standard Python packaging and environment practices for dependencies and tooling.
- Use middleware, context providers, and orchestration patterns in ways that fit the Python application structure.
- Check the latest Python samples before introducing new APIs or workflow patterns.
