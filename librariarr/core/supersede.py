"""Supersession: the only destructive operation on managed data.

A file in the managed tree is removed in exactly one situation — an Arr-side
import replaces it — and even then it is quarantined to
``<managed_root>/.deletedByLibrariarr/`` unless the deployment opted into hard
deletes (``ingest.replacement_delete_mode``). Both reconcilers route every such
removal through here, so the invariant holds with no exceptions to remember.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .fsops import inode_of, move_to_trash, remove_file
from .model import Action, ReconcileReport

LOG = logging.getLogger(__name__)

MODE_HARD = "hard"


def supersede_managed_file(
    path: Path,
    *,
    managed_root: Path | None,
    mode: str,
    kind: str,
    report: ReconcileReport,
    dry_run: bool,
) -> bool:
    """Quarantine (default) or delete one superseded managed file.

    Returns False only when nothing could be done safely: without a managed root
    there is no quarantine location, and destroying the file instead is not an
    option the caller gets to choose.
    """
    if not path.exists():
        return True  # already gone (e.g. a stale entry in a superseded list)
    if mode == MODE_HARD:
        remove_file(path, dry_run=dry_run)
        report.add(Action("unlink", f"superseded managed {kind} removed", str(path), None))
    elif managed_root is None:
        report.warn(
            f"Cannot quarantine superseded {kind} {path}: it is not under any configured "
            "managed root; leaving it in place"
        )
        return False
    else:
        destination = move_to_trash(path, managed_root, dry_run=dry_run)
        report.add(
            Action("trash", f"superseded managed {kind} quarantined", str(path), str(destination))
        )
    report.items_changed += 1
    return True


def rescue_replaced_target(
    source: Path,
    target: Path,
    *,
    managed_root: Path | None,
    mode: str,
    kind: str,
    report: ReconcileReport,
    dry_run: bool,
) -> bool:
    """Supersede a managed file that an incoming hardlink is about to overwrite.

    ``ensure_hardlink`` replaces an existing target by unlinking it first, so an
    import whose filename happens to match the managed file it replaces would
    destroy that file outright — no quarantine, and irrecoverably when the
    managed copy had no other link. A *differently* named import is caught by
    ordinary supersession after the fact; a same-named one is only caught here.

    Returns True when the hardlink may proceed. False means the managed file
    could not be moved out of the way, so the caller must not overwrite it.
    """
    target_inode = inode_of(target)
    if target_inode is None:
        return True  # nothing there to lose
    if target_inode == inode_of(source):
        return True  # already the same file; ensure_hardlink will no-op
    return supersede_managed_file(
        target,
        managed_root=managed_root,
        mode=mode,
        kind=kind,
        report=report,
        dry_run=dry_run,
    )
