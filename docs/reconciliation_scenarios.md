# Reconciliation Scenarios and Coverage

Status: living document for runtime behavior + test coverage

## What Reconciliation Means

In LibrariArr, **reconciliation** is one full convergence cycle that makes Arr state,
managed folders, and library/shadow projections consistent again.

One reconcile cycle does this in order:

1. Consume webhook-scoped IDs (Radarr/Sonarr).
2. Optionally ingest movie/series content from library/shadow roots back to managed roots (`ingest.enabled`).
3. Normalize Arr paths to canonical library/shadow folder layout.
4. Project managed files to library/shadow roots via hardlinks.
5. Run discovery/auto-add for unmatched managed folders.
6. Run conservative stale-shadow cleanup for provenance-managed stale outputs.

Reconcile can be:

- **Scoped/incremental**: only affected IDs or paths.
- **Full**: whole inventory drift-healing pass.

## Production Note: Broken `.librariarr` Series Links on Host

Observed on DiskStation host:

- Broken entries exist under `/volume2/series/.librariarr/FSK06|FSK12|FSK16`.
- These entries are **directory symlinks** pointing to absolute `/data/series/...` targets.
- From host view, `/data/...` is container-internal and therefore appears invalid.

Example observed target pattern:

- `.librariarr/FSK12/Heartstopper -> /data/series/FSK12/Heartstopper`

Root cause:

- These are legacy symlink artifacts from older Sonarr shadow-link behavior.
- Current runtime projection is hardlink-based (file-level) and does not create new
  directory symlinks in production code.

How to verify quickly on host:

```bash
cd /volume2/series
find .librariarr -maxdepth 2 -xtype l -print
```

How to clean safely (broken symlinks only):

```bash
cd /volume2/series
find .librariarr -xtype l -delete
```

Important:

- `-xtype l` removes only broken symlinks.
- This does not remove real directories/files.
- If you want a dry run first, use `-print` instead of `-delete`.

## Scenario Matrix

The scenarios below are intentionally ordered the same for Radarr and Sonarr.

| # | Scenario | Reconcile steps performed to achieve goal | Radarr expected result | Sonarr expected result | FS e2e coverage | Implementation gap |
|---|---|---|---|---|---|---|
| 1 | New Arr import in library/shadow root | webhook/file event -> scope IDs -> ingest (if configured) -> path normalization -> projection | New movie folder is moved to managed root, then projected back to canonical library folder | New series folder is moved from shadow to nested managed root, then projected back to canonical shadow folder | Radarr: yes (`tests/e2e/filesystem/test_ingest.py::test_ingest_moves_matching_folder_from_library_to_managed`), Sonarr: yes (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_full_reconcile_ingests_shadow_folder_to_nested_root`, `tests/e2e/filesystem/test_sonarr_projection.py::test_sonarr_projects_season_subfolder_structure`) | No major gap |
| 2 | Quality/file replacement | webhook/file event -> scope IDs -> ingest file-level (if configured) -> projection relink | New inode/file ends in managed folder and projected path points to new source | New episode file can be ingested from projected shadow path into nested managed root; projection relink then points to new source | Radarr: yes (`tests/e2e/filesystem/test_ingest.py::test_ingest_file_level_when_managed_folder_exists`, `tests/e2e/filesystem/test_config_variants.py::test_relink_on_source_replace`), Sonarr: yes (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_file_level_ingest_moves_shadow_files_into_nested_series`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_relink_on_source_replace`) | No major gap |
| 3 | User rename/move in managed root | file event/full reconcile -> mapping/provenance resolve -> projection -> stale cleanup | Canonical library output updated; no phantom managed folder | Canonical shadow output updated; decorated/non-canonical managed names still resolve | Radarr: yes (`tests/e2e/filesystem/test_projection.py::test_projection_name_mismatch_still_projects_correctly`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_managed_rename_chain_keeps_projection_and_refreshes_stale_state`), Sonarr: yes (`tests/e2e/filesystem/test_sonarr_projection.py::test_sonarr_name_mismatch_projects_canonical`) | No major gap |
| 4 | Manual add in managed root (auto-add unmatched) | discovery scan -> Arr lookup -> conditional auto-add -> projection | Confident match: add+project. No match/ambiguous: skip+retry later | Confident match: add+project. No match/ambiguous: skip+retry later | Radarr: yes (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_radarr_auto_add_success_projects_immediately`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_radarr_auto_add_no_match_retries_after_folder_change`), Sonarr: yes (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_auto_add_success_projects_immediately`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_auto_add_no_match_retries_next_cycle`) | No major gap |
| 5 | Arr path already points to shadow/library location | scope IDs -> resolve mapping/provenance -> normalize path -> projection | Path normalized to flat canonical `Title (Year)` under library root | Path normalized to canonical series folder under shadow root | Radarr: yes (`tests/e2e/filesystem/test_projection.py::test_projection_flattens_nested_library_path`), Sonarr: yes (`tests/e2e/filesystem/test_sonarr_projection.py::test_sonarr_uses_stored_mapping_when_series_path_is_shadow_root`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_nested_shadow_path_is_normalized_to_canonical_shadow_folder`) | No major gap |
| 6 | Extras and unknown files policy | classify files -> apply allowlist -> project -> preserve/replace unknown by config | Video + allowlisted extras projected; unknown preserve/replace follows config | Video + allowlisted extras projected; non-allowlisted skipped | Radarr: yes (`tests/e2e/filesystem/test_config_variants.py`), Sonarr extras: yes (`tests/e2e/filesystem/test_sonarr_projection.py::test_sonarr_projects_series_extras`), Sonarr unknown-policy: yes (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_preserve_unknown_true_keeps_existing_dest`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_preserve_unknown_false_replaces_existing_dest`) | No major gap |
| 7 | Missing managed source folder | resolve IDs -> source existence check -> skip safely | Movie skipped; no invalid projection output | Series skipped; no invalid projection output | Radarr: yes (`tests/e2e/filesystem/test_projection.py::test_missing_managed_folder_skips_projection`), Sonarr: yes (`tests/e2e/filesystem/test_sonarr_projection.py::test_sonarr_missing_nested_folder_skips`) | No major gap |
| 8 | Duplicate prevention / no back-ingest of projection output | reconcile cycle repetition -> ingest guardrails -> projection idempotency | Projection folders are not moved back into managed root as duplicates | Projected shadow output does not trigger duplicate folder moves; only new files are ingested into existing nested source | Radarr: yes (`tests/e2e/filesystem/test_ingest.py::test_ingest_no_duplicate_when_nested_movie_has_projections`), Sonarr: yes (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_file_level_ingest_moves_shadow_files_into_nested_series`, `tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_duplicate_guard_keeps_projection_folder_in_shadow`) | No major gap |

Manual/full/startup reconcile note:

- Desired state is expected to converge regardless of trigger source (webhook, file event, manual API reconcile, or startup reconcile), because all paths run the same reconcile orchestration (`reconcile()` / `reconcile_full()`).
- Manual full reconcile explicitly uses `reconcile_full()` via maintenance operations.
- Startup reconcile can run full or targeted reconcile depending on `runtime.startup_reconcile_mode` (`full`/`smart`), and in `smart` mode it may skip when no baseline drift is detected.
- Therefore, startup mode affects *when/how much* work runs, but not the target converged state once a reconcile cycle executes.

## Implementation Gaps (Current)

No critical reconcile-path implementation gaps are currently open in this matrix.

Recent hardening completed:

1. Added explicit Sonarr nested shadow-path flatten variant coverage (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_sonarr_nested_shadow_path_is_normalized_to_canonical_shadow_folder`).
2. Added startup-trigger Sonarr runtime parity coverage (`tests/e2e/filesystem/test_scenario_gap_coverage.py::test_startup_full_reconcile_projects_sonarr_series`).

## Related Docs

- Runtime flow summary: `docs/workflows.md`
- Radarr architecture deep-dive: `docs/radarr_projection_implementation_spec.md`
- Configuration reference: `docs/configuration.md`