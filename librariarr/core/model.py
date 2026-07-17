"""Plan/report data model for inode-based reconcile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Action:
    """One planned or executed filesystem/Arr operation."""

    kind: str  # link | relink | ingest_link | trash | unlink | add_to_arr | rescan | warn
    detail: str
    source: str | None = None
    target: str | None = None


@dataclass
class UnmatchedFolder:
    path: str
    parsed_title: str | None
    parsed_year: int | None
    # no_match | ambiguous | lookup_failed | auto_add_disabled | add_failed
    # | unparseable | duplicate | already_in_arr
    reason: str
    candidates: list[str] = field(default_factory=list)


@dataclass
class ReconcileReport:
    dry_run: bool = False
    scope: str = "consistency"  # consistency | full | manual-add
    actions: list[Action] = field(default_factory=list)
    unmatched: list[UnmatchedFolder] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    items_seen: int = 0
    items_changed: int = 0
    duration_seconds: float = 0.0

    def add(self, action: Action) -> None:
        self.actions.append(action)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def bump(self, key: str, amount: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "scope": self.scope,
            "stats": dict(self.stats),
            "items_seen": self.items_seen,
            "items_changed": self.items_changed,
            "duration_seconds": round(self.duration_seconds, 3),
            "actions": [
                {
                    "kind": action.kind,
                    "detail": action.detail,
                    "source": action.source,
                    "target": action.target,
                }
                for action in self.actions
            ],
            "unmatched": [
                {
                    "path": item.path,
                    "parsed_title": item.parsed_title,
                    "parsed_year": item.parsed_year,
                    "reason": item.reason,
                    "candidates": item.candidates,
                }
                for item in self.unmatched
            ],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
