"""Catalog color requests and the shared swarm budget.

A grant is usable only on the following round, and only by the requester.
"""

from __future__ import annotations


def catalog_enabled(supplier_cfg: dict | None) -> bool:
    """The catalog is off when `enabled: false` or `swarm_budget: 0`. Validates both keys."""
    cfg = supplier_cfg or {}
    enabled = cfg.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("supplier.enabled must be a boolean")
    budget = cfg.get("swarm_budget", 4)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError("supplier.swarm_budget must be a non-negative integer")
    return enabled and budget > 0


class Supplier:
    def __init__(self, catalog: list[str], swarm_budget: int = 4, enabled: bool = True):
        self.catalog = list(catalog)
        self.swarm_budget = swarm_budget
        self.enabled = bool(enabled) and swarm_budget > 0
        self.granted_total = 0
        self.held: dict[str, set[str]] = {}
        self._arriving: dict[int, dict[str, list[str]]] = {}

    def request(self, agent: str, color: str, round: int) -> dict:
        event = {"type": "deny", "agent": agent, "color": color, "round": round}
        if not self.enabled:
            event["reason"] = "catalog_disabled"
            return event
        if color not in self.catalog:
            event["reason"] = "not_in_catalog"
            return event
        if color in self.held.get(agent, set()):
            event["reason"] = "already_held"
            return event
        if self.granted_total >= self.swarm_budget:
            event["reason"] = "swarm_budget"
            return event
        self.granted_total += 1
        self.held.setdefault(agent, set()).add(color)
        deliver_at = round + 1
        self._arriving.setdefault(deliver_at, {}).setdefault(agent, []).append(color)
        return {
            "type": "grant",
            "agent": agent,
            "color": color,
            "round": round,
            "delivers": deliver_at,
        }

    def deliveries(self, round: int) -> dict[str, list[str]]:
        """Colors whose grant happened last round. Consumed once."""
        found = self._arriving.pop(round, {})
        return {agent: list(colors) for agent, colors in found.items()}
