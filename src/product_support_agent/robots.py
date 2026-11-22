from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

ROBOTS_AGENT_NAME = "product-support-agent"
MAX_ROBOTS_BYTES = 524_288


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str
    expression: re.Pattern[str]


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    expression = "^" + re.escape(body).replace(r"\*", ".*")
    return re.compile(expression + ("$" if anchored else ""))


@dataclass(frozen=True)
class RobotsPolicy:
    """RFC 9309 robots rules for one host: wildcards, `$` anchors, longest match wins."""

    rules: tuple[_Rule, ...] = field(default_factory=tuple)
    disallow_all: bool = False

    @classmethod
    def allow_all(cls) -> RobotsPolicy:
        return cls()

    @classmethod
    def deny_all(cls) -> RobotsPolicy:
        return cls(disallow_all=True)

    @classmethod
    def parse(cls, text: str, user_agent: str = ROBOTS_AGENT_NAME) -> RobotsPolicy:
        groups: list[tuple[set[str], list[_Rule]]] = []
        agents: set[str] = set()
        rules: list[_Rule] = []
        in_rules = False
        for raw_line in text.lstrip("﻿").splitlines():
            line = raw_line.split("#", 1)[0].strip().replace("：", ":")
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:
                    groups.append((agents, rules))
                    agents, rules, in_rules = set(), [], False
                agents.add(value.lower())
            elif key in ("allow", "disallow") and agents:
                in_rules = True
                if not value:
                    continue
                pattern = value if value.startswith(("/", "*")) else "/" + value
                rules.append(_Rule(key == "allow", pattern, _compile(pattern)))
        if agents:
            groups.append((agents, rules))

        token = user_agent.lower()
        specific = [rules for names, rules in groups if token in names]
        wildcard = [rules for names, rules in groups if "*" in names]
        selected = specific or wildcard
        return cls(rules=tuple(rule for group in selected for rule in group))

    def is_allowed(self, url: str) -> bool:
        if self.disallow_all:
            return False
        parsed = urlparse(url)
        target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        best: _Rule | None = None
        for rule in self.rules:
            if not rule.expression.match(target):
                continue
            if (
                best is None
                or len(rule.pattern) > len(best.pattern)
                or (len(rule.pattern) == len(best.pattern) and rule.allow)
            ):
                best = rule
        return best is None or best.allow


def policy_for_status(status_code: int, text: str) -> RobotsPolicy:
    """Map a robots.txt response to a policy.

    Only a missing file (404/410) allows everything. Authorization failures, redirects, and
    server errors fail closed, which is stricter than RFC 9309 for unverified source terms.
    """
    if 200 <= status_code < 300:
        return RobotsPolicy.parse(text)
    if status_code in (404, 410):
        return RobotsPolicy.allow_all()
    return RobotsPolicy.deny_all()
