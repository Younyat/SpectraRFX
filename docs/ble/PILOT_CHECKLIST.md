# BLE Paper Campaign — Qualification Pilot Checklist

This is a checklist for a human operator running REAL hardware. No part of
this pilot was executed or simulated by the assistant that wrote this
document — see the confirmation at the bottom.

**Purpose**: verify the new metadata capture, real 10 s decision windows,
association timing residuals, record separation, and the frozen-schedule
runner all work correctly against a small, real capture batch — **before**
committing to the full 20-day campaign. This pilot's data must never be
used to train, select, or evaluate any model, and must never be treated as
paper evidence.

**Scope** (fixed, do not expand without re-freezing a new schedule):
- 2 physical units
- 2 days
- pre AND post capture for each unit each day
- exactly one RESET arm and one CONTROL arm
- channel 37 only
- one packet-content configuration (`packet_variant="original"`)

## 1. Before any capture

1. Register both physical units in the Physical Device Registry if not
   already present (`POST /ble-rffi-studio/physical-units`).
2. Freeze a protocol via `POST /api/ble-scientific-results/protocols`
   (`hardware_profile_id`, `receiver_profile_hash`, `interpretation_matrix_hash`
   are required; leave `channels=[37]`).
3. Freeze the schedule with `PaperCampaignRunner.freeze_schedule(...)`
   (`backend/app/modules/ble_rffi_studio/campaign/paper_campaign_runner.py`),
   one `PaperCampaignScheduleEntry` per planned capture -- 2 units x 2 days
   x (pre + post) = 8 entries minimum, each with `day_id`, `pre_or_post`,
   `intervention_arm` (`RESET` or `CONTROL`, split evenly), `packet_variant`,
   `channel=37`, `receiver_epoch`, and any of `firmware_hash`/
   `configuration_hash`/`ambient_temperature_c`/`battery_id`/
   `battery_voltage_pre_v`/`operator_id` you can supply. Set
   `qualification_only=True` on the schedule itself.
4. Confirm `runner.next_planned_capture(schedule)` returns the first entry
   before touching the B200.

## 2. For each planned capture

1. Call `runner.execute(schedule, planned_capture_id, build_capture_record=...)`
   -- this performs the real capture (via the existing, unchanged
   `CampaignOrchestrator.run_session()`) and writes the declared metadata
   onto the resulting `capture_manifest.json` immediately afterward.
2. If a capture must happen that is NOT the next scheduled entry, do
   **not** improvise -- call `runner.reject_out_of_schedule(...)` first to
   record the rejection, then either re-freeze a corrected schedule
   version or postpone.
3. Record `battery_voltage_post_v` for the unit right after the capture if
   you are tracking it (there is no automated sensor for this -- it stays
   `null` unless you supply it).

## 3. After all 8+ captures

1. In BLE-RFFI Studio, run replay + Evidence Stage for every new capture
   (existing flow, unchanged).
2. Build a dataset from these captures (`build_dataset`), then a split
   (`build_split`, `TARGET_VS_BACKGROUND` or whichever task applies).
3. In BLE Scientific Results Studio: freeze a run against this dataset,
   run `POST .../build-records`, then check:
   - `GET .../campaign-accounting`: `observed_captures` should equal the
     number of executed schedule entries; `protocol_deviation_count`
     should be 0 unless something genuinely went off-schedule.
   - `GET .../captures`: every capture should show `day_id`, `pre_or_post`,
     `intervention_arm`, `packet_variant`, `receiver_epoch` populated
     (not `null`) -- if any is `null`, the metadata plumbing did not work
     and must be fixed before the real campaign.
   - `GET .../runs/{id}/windows` (via the records tables): confirm windows
     are real 10 s slices (`window_duration_s=10`), not one window per
     candidate.
   - `04_quality/association_timing_residual_distribution.csv`: confirm
     it has real, non-empty rows.

## 4. Mark the pilot as non-paper data

1. Confirm the schedule's `qualification_only=True` was preserved (it is
   immutable once frozen).
2. In any dataset/paper-run built from this pilot's captures, record
   `CAMPAIGN_QUALIFICATION_ONLY` / `EXCLUDED_FROM_PAPER_RESULTS` in your
   own notes for that dataset_id -- there is no dedicated field for this
   yet on `DatasetManifest` itself; treat the schedule's own
   `qualification_only=True` flag as the authoritative marker and never
   reference this dataset_id from a paper-results run.
3. Do not train, select thresholds for, or calibrate any model against
   this data.

---

**Confirmation**: this checklist was written without executing any of the
steps above. No real capture, no real schedule, and no real dataset were
created as part of producing this document -- the pilot itself must be run
by a human operator with real hardware present.
