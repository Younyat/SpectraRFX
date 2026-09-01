# Storage & Artifact Repository Management

Real, filesystem-grounded disk-usage inventory for everything under
`backend/app/infrastructure/persistence/storage/`, plus a confirmation-gated
per-artifact deletion tool. Built to answer "what is eating my disk, and can
I safely delete it" without guessing.

Always enabled (no feature flag) -- it is read-mostly and additive: it
introduces no new route or behavior anywhere else in the platform.

## What it shows

- **Overview**: total bytes and file count on disk, plus a bar chart of the
  top-level storage categories (`ble`, `scientific_reports`, `ble_rffi_studio`,
  `mlops`, ...) by real, measured size.
- **Drill-down**: click a category to see its contents. `ble/iq_captures`
  gets special handling -- instead of one opaque 60+ GB folder, it lists
  every individual capture, enriched with real fields from that capture's
  own `capture_manifest.json` (`created_at_utc`, `ble_channel`,
  `dataset_eligible`, `scientific_campaign_member`, ...), reusing
  `BleCaptureJobManager.list_captures()` rather than recomputing anything.
  Every other category is shown as plain directory/file entries with real
  size and modification time.
- **Preserved flag**: a disclosed heuristic, not a hard block. Every BLE I/Q
  capture defaults to `preserved=true` (it is primary, irreplaceable
  evidence). Everything else defaults to `preserved=true` too, *unless* its
  path matches a known regenerable-cache/temp naming pattern (`temp`, `tmp`,
  `cache`, `logs`, `offline_replays`, `__pycache__`), in which case it is
  `preserved=false`. The flag only changes how strongly the delete
  confirmation warns -- it never blocks deletion outright, since the
  operator (not a heuristic) is the one who actually knows what is safe to
  remove.

## Deletion

`DELETE /api/storage-management/items` requires an explicit `confirm: true`
in the request body; the frontend never sends that without the operator
first confirming a modal that shows the artifact's name, size, and the
same preserved/regenerable reasoning shown in the list. There is no
"undo" -- deletion is a real `shutil.rmtree`/`Path.unlink` against the real
storage root, path-traversal-guarded to never touch anything outside it.

## Known scope boundary

Deletion and drill-down are per-directory-entry -- there is no bulk
"delete everything older than N days" tool. The `offline_replays/` bloat
found and cleaned up on 2026-08-31/09-01 (150 folders, 2.51 GB, 252,216
files, all regenerable BLE offline-replay retry artifacts) is exactly the
kind of thing this module now makes visible and deletable through the UI
going forward, instead of requiring an ad hoc PowerShell scan.
