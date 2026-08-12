"""Bucket relocation: the single place a managed folder moves between buckets.

Scenario 11 (see docs/reconciliation_scenarios.md): the user reassigns an
item's root folder in Radarr/Sonarr, so its Arr path now maps to a different
configured bucket than the one its managed folder lives under. That is a
deliberate reclassification, and the managed folder follows -- as a real
same-filesystem rename, which preserves the inode and therefore leaves the
Arr-side hardlink untouched.

Shared by the movie and series reconcilers so that every scope (full,
consistency, targeted) applies identical rules. Divergent relocation rules per
trigger would mean an item that a targeted pass refuses to move gets moved by
the next full pass anyway -- the sort of split-brain behavior the single
canonical scenario matrix exists to prevent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .fsops import prune_empty_dirs
from .model import Action, ReconcileReport

LOG = logging.getLogger(__name__)

# Machine-readable refusal reasons (also surfaced by the API).
BLOCKED_DESTINATION_EXISTS = "destination_exists"
BLOCKED_CROSS_FILESYSTEM = "cross_filesystem"
BLOCKED_AMBIGUOUS_OWNER = "ambiguous_owner"
BLOCKED_UNKNOWN_ROOT_MAPPING = "unknown_root_mapping"


@dataclass(frozen=True)
class RelocationOutcome:
    folder: Path
    """The managed folder to use from here on: the new location after a
    successful move, otherwise the unchanged original."""

    relocated: bool = False
    """True when a relocation was reported. The filesystem only changed if the
    call was not a dry run (a dry run reports the move and keeps ``folder`` at
    the original location, so the rest of the pass stays consistent)."""

    blocked: str | None = None
    """Machine-readable reason a needed relocation was refused, if any."""


def relocate_managed_folder(
    managed_folder: Path,
    *,
    target_root: Path,
    current_root: Path | None,
    label: str,
    arr_name: str,
    report: ReconcileReport,
    dry_run: bool,
    other_owners: Iterable[int] = (),
) -> RelocationOutcome:
    """Move ``managed_folder`` into ``target_root``, preserving its relative path.

    Refuses (warns, touches nothing) rather than overwriting or merging. On
    every refusal the returned outcome carries a ``blocked`` reason and the
    original folder, so callers continue to work against the location that
    actually exists on disk.

    ``other_owners`` are the ids of *other* Arr items whose cached managed
    folder is this same folder. Any such collision blocks the move: a folder
    with two claimed owners cannot be reclassified on behalf of one of them
    without silently reclassifying the other.
    """
    if current_root is None or current_root == target_root:
        return RelocationOutcome(managed_folder)
    try:
        relative = managed_folder.relative_to(current_root)
    except ValueError:
        # Unreachable by construction (current_root is derived from the folder
        # via is_within); reported rather than guessed at if it ever happens.
        return RelocationOutcome(managed_folder, blocked=BLOCKED_UNKNOWN_ROOT_MAPPING)

    destination = target_root / relative
    conflicts = sorted({int(owner) for owner in other_owners})
    if conflicts:
        return _refuse(
            report,
            BLOCKED_AMBIGUOUS_OWNER,
            managed_folder,
            f"'{label}' should move from bucket '{current_root}' to '{target_root}', but "
            f"{managed_folder} is also claimed by {arr_name} id(s) "
            f"{', '.join(str(i) for i in conflicts)}; refusing to relocate a managed folder "
            "with more than one owner",
        )
    if destination.exists():
        return _refuse(
            report,
            BLOCKED_DESTINATION_EXISTS,
            managed_folder,
            f"'{label}' is in bucket '{current_root}' but {arr_name} now has it under "
            f"'{target_root}'; cannot auto-relocate because {destination} already exists",
        )
    if not _same_filesystem(managed_folder, destination):
        return _refuse(
            report,
            BLOCKED_CROSS_FILESYSTEM,
            managed_folder,
            f"'{label}' cannot be relocated from '{current_root}' to '{target_root}': the two "
            "buckets are on different filesystems, so the move would become a copy and break "
            "inode identity",
        )

    report.items_changed += 1
    report.add(
        Action(
            "relocate",
            f"moved to bucket matching {arr_name}'s root folder for '{label}'",
            str(managed_folder),
            str(destination),
        )
    )
    if dry_run:
        return RelocationOutcome(managed_folder, relocated=True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    managed_folder.rename(destination)
    prune_empty_dirs(current_root, dry_run=False)
    LOG.info("Relocated managed folder %s -> %s", managed_folder, destination)
    return RelocationOutcome(destination, relocated=True)


def _refuse(report: ReconcileReport, reason: str, folder: Path, message: str) -> RelocationOutcome:
    report.warn(message)
    report.bump(f"relocations_blocked_{reason}")
    return RelocationOutcome(folder, blocked=reason)


def _same_filesystem(source: Path, destination: Path) -> bool:
    """Whether a rename from source to destination stays on one filesystem.

    ``check_single_filesystem`` already refuses to start when *configured*
    roots span filesystems; this is the per-move backstop for anything that
    changed underneath a running process (a remounted bind mount, say). When
    the answer cannot be determined the move proceeds and the rename itself
    decides -- an unstattable path fails there anyway.
    """
    anchor = next((parent for parent in destination.parents if parent.exists()), None)
    if anchor is None:
        return True
    try:
        return source.stat().st_dev == anchor.stat().st_dev
    except OSError:
        return True
