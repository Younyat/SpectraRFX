# IEEE 802.11 (Wi-Fi) demodulation — technical README

Audience: a programmer with **no prior context** who needs to understand,
reproduce, extend, or debug the Wi-Fi decoding capability in this platform.

Status honesty, up front: this is a **partial-recovery** passive receiver. On
a real over-the-air capture it has recovered genuine IEEE 802.11 beacon and
data frames (including readable SSIDs), but it does **not** recover every
transmitted frame, even on a clean channel. That loss is a known, still-open
problem — it is not something this integration work tried to fix, and nothing
in this document should be read as claiming full/complete recovery. See
[§8 Known open problem](#8-known-open-problem-partial-frame-recovery).

---

## 1. What this capability actually is

A pinned, isolated build of `gr-ieee802-11` (a GNU Radio out-of-tree module
implementing legacy 802.11a/g OFDM PHY + MAC) is invoked as an external
subprocess from this platform's backend to decode real captured IQ. When it
recovers a frame, that frame has **already passed the standard Wi-Fi FCS
(CRC-32) check** inside the decoder — so every frame this platform reports as
"confirmed" is a real, validated IEEE 802.11 frame, not a candidate or a
guess. What's still incomplete is that not every frame present in a capture
gets recovered; the receiver silently drops some fraction of them, and the
root cause of that residual loss has not been fixed (it's a separate, ongoing
investigation outside the scope of this platform's own code — see §8).

This document covers the **integration** of that pinned decoder into
spectrum-lab: how a capture gets from "IQ file on disk" or "USRP antenna" to
"confirmed frames rendered in the browser." It does **not** cover how the
pinned `gr-ieee802-11` build itself was compiled/patched — that happened in a
separate, external lab (`C:\Users\Usuario\wifi-worker-lab`, outside this
repo) across an earlier campaign (builds V1 through V5b). Only **V3** is
used in production; V4/V5/V5b were experimental attempts at fixing the
residual frame loss that ended up regressing recovery rate and were
deliberately never wired into this platform. If `wifi-worker-lab` doesn't
exist on a machine, everything below still runs, but silently falls back to a
much weaker RF-burst-candidate scaffold (see §7) — Wi-Fi demodulation is not a
hard dependency of this repo.

---

## 2. Architecture: how a capture becomes a confirmed frame

```
                         ┌─────────────────────────────────────────────┐
                         │  spectrum-lab backend (FastAPI, this repo)   │
                         │                                              │
IQ file on disk  ───────►│  WifiCaptureContract  ──►  WifiDecodeService │
  (Capture Lab /         │  (validates metadata)      .decode()        │
   Dataset Builder)      │                                │             │
                         │                                ▼             │
Live USRP-B200   ───────►│  demodulate_marker_band()  (forces 20 MS/s   │
  (Live Demodulation /   │   for mode=wifi_80211)         │             │
   Wi-Fi Dashboard)      │                                ▼             │
                         │                    GrIeee80211Worker.run()   │
                         │                    (subprocess boundary --   │
                         │                     no GPL/GNU Radio code    │
                         │                     ever runs inside FastAPI)│
                         └────────────────────────────┼─────────────────┘
                                                       │ spawns
                                                       ▼
                         ┌─────────────────────────────────────────────┐
                         │ wifi-worker-env\python.exe (pinned, separate │
                         │ interpreter -- GNU Radio 3.10.12.0 install)  │
                         │                                              │
                         │  backend/tools/wifi_80211_v3_worker.py       │
                         │   loads IQ, builds an RX-only flowgraph      │
                         │   using instrumented-prefix-v3's             │
                         │   wifi_phy_hier (validated V3 build),        │
                         │   collects "mac_out" messages                │
                         │   (each one already FCS-verified)            │
                         └────────────────────────────┼─────────────────┘
                                                       │ worker_result.json
                                                       ▼
                         ┌─────────────────────────────────────────────┐
                         │ WifiDecodeService._merge_worker_result()     │
                         │  -> mac_parser.parse_mpdu() for each frame   │
                         │  -> decoded_frames.json, demodulation_report │
                         │     .json, receiver_internal_events.jsonl    │
                         └────────────────────────────┼─────────────────┘
                                                       │
                                                       ▼
                    Capture Lab button / Dataset Demodulation / Live
                    Demodulation / Wi-Fi Dashboard (frontend, React)
```

Two interpreters are involved on purpose: the FastAPI backend's own venv
(`backend/venv`) never imports GNU Radio. The pinned GNU Radio environment
(`wifi-worker-env\python.exe`) only ever runs as a short-lived subprocess
invoked with `--manifest <path> --output-dir <path>`, communicating purely
through files on disk (manifest in, `worker_result.json` + diagnostics out).
This mirrors the platform's existing `RADIOCONDA_PYTHON` split convention
used for the SDR capture workers, and keeps GPL-licensed code fully
out-of-process (see `THIRD_PARTY.md`).

---

## 3. The pinned V3 receiver

| Item | Pin |
|---|---|
| GNU Radio | `3.10.12.0` |
| `gr-ieee802-11` commit | `ad0598e4a874f4b8e1f391a1e0323e80df2b34ff` |
| `gr-foo` commit | `4c2a471b0453b9dca669b2d9dfcbfba6278741d7` |
| Build location | `C:\Users\Usuario\wifi-worker-lab\instrumented-prefix-v3` |
| Interpreter | `C:\Users\Usuario\wifi-worker-lab\wifi-worker-env\python.exe` |
| `gnuradio-ieee802_11.dll` SHA-256 | `dcdcb8b6893179904eeb104d45f0b61360ce21678b5d051ceb0ff4e532408c02` |
| `ieee802_11_python.cp312-win_amd64.pyd` SHA-256 | `e6bc159d032de5840d3641143b5bb90e898c42e6353ad7f72be25d77545a3095` |

These hashes are the **authoritative pin check**, not `importlib.metadata` —
the build is loaded via `sys.path` override (not pip/conda install), so
package metadata would report the unrelated default RadioConda package
instead of what's actually imported. `wifi_80211_v3_worker.py` computes them
at every run and writes both the pinned and detected values into
`software_versions.json`, so every decode result carries proof of which
binary actually produced it. A mismatch is recorded but does not, by itself,
fail the run — it's evidence for audit, not an automatic abort.

`instrumented-prefix-v3` is a **campaign-instrumented** build: it writes a
structured JSONL diagnostic trace (`receiver_internal_events.jsonl`) at every
pipeline stage (`sync_short`, `sync_long`, `frame_equalizer`, `decode_mac`),
which is exactly what makes the residual frame-loss problem (§8) debuggable
instead of a black box. This instrumentation is why V3, specifically, is the
one used here — V4/V5/V5b experimented with changes to the receiver itself
(an admission gate, internal trace-id generation) and are **not** used in
production; they live only in `wifi-worker-lab` for historical reference.

---

## 4. Mathematical / DSP techniques implemented in this repo

Everything in §3 lives in the external, pinned GNU Radio build and is out of
this repo's scope to reproduce. What follows is implemented **in this repo**
(`backend/app/modules/demodulation/wifi_80211/`), independent of the V3
worker being available at all.

### 4.1 L-STF periodicity detection (preamble *candidate*, not decoding)

`infrastructure/legacy_ofdm_decoder.py::find_stf_candidates()` implements a
classic delay-and-correlate (Schmidl & Cox style) periodicity metric. IEEE
802.11's Short Training Field repeats every 16 samples at 20 MS/s, so:

```
products[n] = iq[n] * conj(iq[n + 16])          # 16-sample-lag autocorrelation
energy[n]   = |iq[n + 16]|^2
P(n)        = moving_sum(products, window=64)    # boxcar accumulation
R(n)        = moving_sum(energy,   window=64)
M(n)        = |P(n)|^2 / (R(n)^2 + 1e-20)        # normalized, bounded ~[0,1]
```

`M(n) >= 0.75` sustained for at least 24 samples ("plateau") is reported as a
`preamble_candidate` with its peak correlation and plateau length. This is
**evidence only** — it detects the right periodic structure exists in the
band, it does not decode a frame. It's what still runs even when the V3
worker is unavailable, and its candidates are always reported separately from
confirmed frames (`preamble_candidates` vs `frames_decoded` in the report).

### 4.2 FCS verification via CRC-32 residue check (inside the pinned worker, surfaced here)

`gr-ieee802-11`'s `decode_mac` block verifies FCS using the CRC-32 residue
property: computing the standard CRC-32 over `(message || its own correct
FCS)` always yields a fixed constant (`558161692` in this build's
convention), independent of message content. This is mathematically
equivalent to recomputing CRC-32 over the message and comparing to the
transmitted trailer, but avoids having to separately extract/parse the
trailer. **Only frames that pass this check are published** on the
`mac_out` message port — this is what "confirmed frame" means throughout
this platform; there is no separate, lower-confidence "candidate frame" tier
downstream of the worker.

Important, non-obvious detail discovered during integration: `decode_mac`
strips the 2-byte SERVICE field *and* the trailing 4-byte FCS before
publishing (`pmt::make_blob(out_bytes + 2, psdu_size - 4)` in
`decode_mac.cc`) — the published PDU has **no FCS trailer left in it at
all**. `mac_parser.py`'s original contract assumed a trailing FCS to
re-slice and recompute (see §6.1 for why, and the bug this caused).

### 4.3 SSID information-element extraction

`infrastructure/mac_parser.py::_extract_ssid()` parses the IEEE 802.11
management-frame body to recover the SSID from `beacon`/`probe_response`
(12 fixed bytes — 8-byte timestamp + 2-byte beacon interval + 2-byte
capability info — then tagged parameters) and `probe_request` (no fixed
bytes, tagged parameters start immediately). In both cases the SSID element
is `tag_number == 0`; its length-prefixed value is decoded as UTF-8
(`errors="replace"`, defensive — never raises on malformed/truncated
payloads, it just omits the field). Verified against a real over-the-air
capture: recovered `"eduroam"` and `"WifiUma"` correctly from real beacon
bytes (see §5 for the artifact).

---

## 5. Code walkthrough (file by file)

### `backend/tools/wifi_80211_v3_worker.py` (new)
Runs under the pinned `wifi-worker-env\python.exe`, invoked as
`<python.exe> wifi_80211_v3_worker.py --manifest <path> --output-dir <path>`.
Self-contained (no imports from `backend/app` — this script has no access to
the backend's own packages, it's a different interpreter). Responsibilities:
- `check_environment()` — computes and records the binary hashes from §3.
- `load_iq()` — reads `cf32_le`/`ci16_le`/`cu8` into complex64 (own,
  self-contained loader).
- `run_decoder()` — builds a `gr.top_block` with a local `IqSource`
  (`gr.sync_block`, file-backed) → `wifi_phy_hier(20e6, Equalizer(0),
  Encoding(0), channel_center_hz, 0.56)` (from `instrumented-prefix-v3`) →
  `null_sink` (TX side unused) + `mac_out` message → a local `RxSink`
  (`gr.basic_block`) that collects each PDU as it arrives. Sets
  `WIFI_CAMPAIGN_RUN_ID`/`WIFI_CAMPAIGN_EVENTS_DIR` env vars so V3's existing
  instrumentation writes `receiver_internal_events.jsonl` straight into this
  run's own output dir — no new instrumentation code needed.
- Writes `worker_result.json` (`status`, `frames: [{mpdu_hex,
  arrival_order}]`, `receiver_diagnostics_summary` — counts pulled from the
  JSONL trace — and `decoder_version`), `software_versions.json`. Exit 0
  whenever the flowgraph ran to completion (0 frames decoded is a valid,
  honestly-reported outcome); non-zero only for real errors.

### `backend/app/modules/demodulation/wifi_80211/domain/models.py`
`WifiCaptureContract` — frozen dataclass, `.validate()` fails closed
(returns a list of missing/invalid fields) unless `datatype` is one of
`cf32_le`/`ci16_le`/`cu8`, `sample_rate_hz`/frequencies are positive,
`sample_count > 0`, and **`temporal_order_known` is truthy**. That last one
caused a real bug — see §6.2.

### `.../infrastructure/mac_parser.py`
`RecoveredPsdu(data, complete, source="validated_phy_worker", fcs_included=True)`
+ `parse_mpdu()`. Fails closed: raises unless `complete=True` and
`source="validated_phy_worker"`. `fcs_included` (added during this
integration, defaults `True` to preserve the original/tested contract)
branches the FCS handling: `True` re-slices the last 4 bytes and recomputes
CRC-32 against them (the original, pre-V3 assumption); `False` treats the
whole payload as body and trusts the upstream worker's own FCS check
(`fcs_valid: True, fcs_verified_by: "phy_worker_upstream_crc32_residue_check"`) —
this is the branch the real V3 worker uses (see §6.1). Masks protected
payloads as `payload_state: "protected_ciphertext"` (never exposes cleartext
for a frame with the `protected` flag set) — this is untouched, original,
tested behavior. §4.3's SSID extraction is called from here.

### `.../application/wifi_decode_service.py`
`WifiDecodeService.decode(contract, output_dir)` — the single orchestrator
every entry point (Capture Lab, Dataset Demodulation, Live Demodulation,
Wi-Fi Dashboard) calls through. Runs `find_stf_candidates()` (§4.1) over the
whole file in bounded chunks (never silently truncates), then — if
`WIFI_GR_IEEE80211_WORKER` is configured or `default_worker_command()`
resolves (see below) *and* `sample_rate_hz == 20_000_000.0` *and*
`hardware_center_frequency_hz == channel_center_frequency_hz` — invokes
`GrIeee80211Worker` and merges its result via `_merge_worker_result()`:
hex-decodes each `mpdu_hex`, calls `parse_mpdu()` with `fcs_included=False`,
and only ever reports `status: "frames_confirmed_partial_recovery"` (never
`"fully_decoded"`/`"complete_recovery"`) when at least one frame is
confirmed. Copies `receiver_internal_events.jsonl` and
`software_versions.json` up into the result's `outputs` so they're
downloadable through the existing `GET /outputs/{id}/{filename}` endpoint
with zero new code. `receiver_diagnostics_summary` (sync_short_accepted,
sync_long_accepted/rejected, l_sig_valid/rejected, fcs_valid/invalid,
frames_abandoned) is a **structured** field in the report (not just
notes text), so a UI can render it as a table without string-parsing.

`default_worker_command()` — makes the real worker the default with **zero
manual configuration**: if `WIFI_GR_IEEE80211_WORKER` isn't set, it resolves
to `wifi-worker-env\python.exe backend/tools/wifi_80211_v3_worker.py`
automatically, but only if both files actually exist on this machine —
otherwise returns `None` and the platform degrades cleanly to the scaffold
(§7) instead of trying to spawn a missing interpreter. This means selecting
`wifi_80211` anywhere in the platform runs the real decoder by default,
today, with no env var to remember.

### `.../infrastructure/gr_ieee80211_worker.py`
`GrIeee80211Worker.run(manifest, output_dir, cancel=None)` — the actual
subprocess boundary. Runs the command with a timeout, writes
`worker_process.json`/`worker.stdout.log`/`worker.stderr.log`, returns a
`WorkerResult(status, exit_code, stdout, stderr, timed_out, cancelled,
duration_seconds)`. `status` is `"complete"` only on exit code 0.

### `backend/app/infrastructure/web/controllers/demodulation_controller.py`
- `demodulate_dataset_capture(payload)` — the Dataset Demodulation /
  Capture-Lab-analyze-existing-recording path. Gated by
  `_wifi_demod_v2_enabled()` (opt-out via `WIFI_DEMOD_V2=false`, defaults
  **on**) and `_wifi_worker_available()` (parses `WIFI_GR_IEEE80211_WORKER`
  the same way `decode()` does — as a possible multi-token command, not a
  single file path — falling back to `default_worker_command()` too, so the
  two checks never disagree about whether a worker is configured).
- `demodulate_marker_band(...)` — the Live Demodulation / Wi-Fi Dashboard
  live-capture path. `_live_capture_sample_rate_hz()` forces exactly
  **20,000,000.0 Hz** for `mode="wifi_80211"` whenever the worker is
  available (legacy 802.11a/g channels are always 20 MHz wide — this
  overrides whatever rate would otherwise be derived from the marker-band
  span the user drew). After capture, routes to `_run_wifi_v2()` (which
  builds a `WifiCaptureContract` and calls `WifiDecodeService().decode()`)
  instead of the generic `_run_iot_pipeline()` scaffold, with the same
  worker-rejection fallback pattern as the dataset path.
- `start_wifi_dataset_job(payload)` / `get_wifi_dataset_job(job_id)` —
  wraps `demodulate_dataset_capture()` in a background thread + the shared
  `job_tracker` (see below), because that route is `async def` in FastAPI
  and calling a slow, blocking decode directly inside it would freeze the
  whole event loop (spectrum/waterfall polling, everything) for the
  duration of the GNU Radio subprocess. `demodulate_marker_band`'s own route
  is a plain `def` (not `async def`), which FastAPI already offloads to a
  thread pool automatically — so it never needed this treatment.
- `list_wifi_channels()` / `_wifi_24ghz_channels()` / `_wifi_5ghz_channels()`
  — single source of truth for channel-number → center-frequency mapping
  (2.4 GHz: `2407 + 5*channel` MHz, channels 1–13; 5 GHz: `5000 + 5*channel`
  MHz, the standard 20/40/80 MHz-grid channel numbers), used by the Wi-Fi
  Dashboard's channel picker.

### `backend/app/infrastructure/jobs/job_tracker.py`
Generic, reusable background-job registry (`create_job`/`update_job`/
`complete_job`/`fail_job`/`get_job`/`list_jobs`/`cleanup_old_jobs`), an
in-memory `dict` + `threading.Lock`, extracted from `e6_oracle_style`'s
original (untouched) copy so any module can share one job-status pattern.
Not Wi-Fi-specific, but Wi-Fi is its first consumer.

### `backend/app/infrastructure/web/api/routes/demodulation_routes.py`
`POST/GET /dataset-capture/wifi-job(/{job_id})` (job-backed analyze),
`GET /wifi-80211/channels` (channel picker data). `DatasetDemodulationBody`
gained `temporal_order_known: bool = True` (fixes §6.2).

### Frontend entry points (all call the same backend, none duplicate logic)
- **Capture Lab** (`ModulatedSignalAnalysisView.tsx`) — a "Demodulate Wi-Fi"
  button per capture row, uses the job endpoints.
- **Modulation → Dataset Demodulation** (`DemodulationView.tsx`) — pipeline
  dropdown `wifi_80211` also routes through the job endpoints (was
  synchronous originally; changed for the same event-loop-blocking reason
  as `start_wifi_dataset_job` above).
- **Modulation → Live Demodulation** (`DemodulationView.tsx`) — same view,
  calls `demodulateMarkerBand` directly (already thread-pool-offloaded by
  FastAPI, no job wrapper needed).
- **Wi-Fi Dashboard** (`WifiDashboardView.tsx`, route `/wifi-dashboard`) —
  the dedicated, Wi-Fi-only workspace: channel picker (backed by
  `GET /wifi-80211/channels`) to trigger a live capture, a dropdown to
  analyze an existing Capture Lab recording, a full report (status,
  frames-confirmed/FCS-valid counts, the structured diagnostics stat grid,
  a frames table with BSSID/SSID/sequence/FCS and a per-frame detail panel,
  notes, and download links for all four output artifacts), and a history
  list across all three other entry points (filtered client-side by
  `pipeline === 'wifi_80211'`).

---

## 6. Bugs found and fixed during integration (read this before touching the code again)

These were all discovered by actually running the pipeline end to end
against real data — not by code review — so they're easy to reintroduce if
this integration is ever redone from scratch without testing against a real
20 MS/s capture.

### 6.1 `mac_parser` assumed a trailing FCS that the real worker doesn't send
Symptom: every confirmed frame showed `fcs_valid: false` (contradicting the
"every frame passed FCS" claim) and payloads were silently missing their
last 4 bytes. Root cause: `decode_mac.cc` strips the FCS before publishing
(§4.2) — there is nothing left to re-slice. Fixed by adding
`RecoveredPsdu.fcs_included` (default `True`, preserves the original
contract/tests) and passing `fcs_included=False` at the one real call site
(`_merge_worker_result`).

### 6.2 `temporal_order_known` silently defaulted to `False`
`DatasetDemodulationBody` had no top-level field for it, so
`_run_wifi_v2` read `data.get("temporal_order_known", False)` — meaning
`WifiCaptureContract.validate()` rejected *every* wifi_80211 request
unconditionally, regardless of worker configuration. Fixed by adding
`temporal_order_known: bool = True` to the request body (Capture Lab
captures are contiguous, temporally-ordered recordings, so `True` is the
correct default for that source).

### 6.3 `_wifi_worker_available()` treated a multi-token command as one file path
`WIFI_GR_IEEE80211_WORKER` can be `"<interpreter> <script>"` (needed because
the worker requires a different interpreter than the backend's own), but
the availability check did `Path(configured).is_file()` on the whole string
— always `False` for a two-token value. Fixed to `shlex.split()` it the same
way `decode()` does, and check each `.exe`/`.py` token individually.

### 6.4 `default_worker_command()`'s quoting broke on Windows
First version wrapped the two paths in double quotes
(`'"<python>" "<script>"'`). `decode()` splits this with
`shlex.split(external, posix=os.name != "nt")` — on Windows, `posix=False`
means quote characters are **preserved literally**, not stripped (that's
the whole point of `posix=False`: it protects single-backslash Windows
paths from being mangled as escape sequences). The quotes ended up as part
of the resolved file path → `WinError 2`. Fixed by not quoting at all
(neither path contains a space, so it isn't needed).

### 6.5 Capture Lab's on-disk datatype label doesn't match the worker's vocabulary
Capture Lab always writes `iq_dtype: "complex64"` regardless of
`file_format`, but the wifi_80211 module's `BYTES_PER_COMPLEX` dict only
recognizes `cf32_le`/`ci16_le`/`cu8`. `_normalize_iq_datatype()` in the
controller already aliases `"complex64"` → `"cf32_le"` for the dataset path,
but the frontend now sends `datatype: 'cf32_le'` explicitly at the one
Capture-Lab call site too, since that's the one true on-disk format Capture
Lab ever produces (interleaved float32 I/Q) — belt and suspenders.

---

## 7. What happens when the V3 worker is not available

Nothing breaks. `default_worker_command()` returns `None` when
`wifi-worker-lab`'s pinned files aren't present, `_wifi_worker_available()`
returns `False`, and every entry point falls back to the pre-existing
generic RF-burst-candidate scaffold (`_run_iot_pipeline`) — the same one
used for BLE-style energy-burst detection. That path reports
`wifi_activity_detected_no_valid_frames` and explicitly says it "detects
Wi-Fi-band RF burst candidates, but does not reconstruct CRC-valid IEEE
802.11 frames." It is **not** Wi-Fi decoding, and its report text is shared
generic scaffold wording (a known, pre-existing cosmetic issue where a
`wifi_80211`-labeled result can say "N BLE packet candidate(s)" — harmless,
but don't mistake it for a V3 failure).

---

## 8. Known open problem: partial frame recovery

The validated V3 receiver does not recover every transmitted frame, even on
a clean channel. A real over-the-air 5-second capture on a live Wi-Fi
channel recovered 117 confirmed frames while the diagnostic trace showed
528 `sync_long_accepted` events, 256 `fcs_invalid`, and 102
`frames_abandoned` — i.e. a substantial fraction of frames that got as far
as synchronization never made it to a confirmed FCS-valid frame. This is a
**known, still-open receiver problem**, root-caused across an earlier,
separate diagnostic campaign (V4's admission gate eliminated abandonment
events but caused a compensating rise in FCS-invalid frames with no net
recovery improvement; V5/V5b's event-driven release channel regressed
recovery to near-zero due to internal buffering delay) — none of those
experimental fixes are used here. Every decode result's
`receiver_internal_events.jsonl` (full per-stage trace) and
`receiver_diagnostics_summary` (aggregate counts) exist specifically so this
problem stays investigable rather than being papered over. Do not attempt to
"fix" this by loosening the FCS check, by accepting `l_sig_rejected`/
`sync_long_rejected` events as frames, or by any change that would make a
non-FCS-valid frame get reported as confirmed.

---

## 9. Reproducing this from scratch on a new machine

1. **Prerequisite (external, not part of this repo):** a working
   `wifi-worker-lab` with `instrumented-prefix-v3` built and
   `wifi-worker-env` (GNU Radio 3.10.12.0 + pinned `gr-ieee802-11`/`gr-foo`)
   at the exact paths in §3. Building that pinned GNU Radio OOT module is
   out of scope for this repo. Without it, everything below still runs, but
   only produces the scaffold's RF-burst-candidate output (§7), never
   confirmed frames.
2. Start the backend normally (`backend/venv/Scripts/python.exe -m uvicorn
   app.main:app`) — **no environment variables need to be set**;
   `default_worker_command()` finds the pinned worker automatically if
   present.
3. Verify the worker directly (bypasses the whole platform, fastest sanity
   check): run `wifi-worker-env\python.exe backend/tools/wifi_80211_v3_worker.py
   --manifest <manifest.json> --output-dir <dir>` against any 20 MS/s
   `cf32_le`/`ci16_le`/`cu8` capture, with a manifest containing at least
   `decoder_sample_rate_hz: 20000000`, `input_file`, `datatype`,
   `sample_rate_hz`, `channel_center_frequency_hz`. Check `worker_result.json`
   for `"status": "complete"` and a `frames` array.
4. Exercise the full platform via any of the four entry points in §5 — they
   all converge on the same `WifiDecodeService.decode()`.

## 10. Verifying an existing setup end to end

- `pytest backend/app/tests/unit/test_wifi_80211_v2.py` — unit-level:
  chunked IQ reading, STF periodicity math, protected-payload masking,
  fail-closed MAC parsing, worker-failure handling. Does not require the
  pinned GNU Radio build (uses the stub worker / synthetic data).
- Hit `GET /api/demodulation/wifi-80211/channels` — confirms channel math
  (`CH1` must be `2412000000.0`).
- Start a job (`POST /api/demodulation/dataset-capture/wifi-job`) against a
  known-good 20 MS/s fixture, poll to `done`, and check the result's
  `frames_decoded > 0`, `receiver_diagnostics_summary` present, and that
  `GET /outputs/{id}/decoded_frames.json` / `.../receiver_internal_events.jsonl`
  both resolve.
- For a genuine end-to-end proof, run a real live capture (Live
  Demodulation or Wi-Fi Dashboard) on an active 2.4/5 GHz channel and look
  for readable SSIDs in the decoded frames' `ssid` field — that's
  unambiguous confirmation the whole chain (USRP → 20 MS/s capture → V3
  worker → FCS-valid frame → MAC parse → SSID extraction → UI) is working
  against real RF, not synthetic fixtures.

---

## 11. File map

```
backend/tools/wifi_80211_v3_worker.py                              (real worker, runs under wifi-worker-env)
backend/app/modules/demodulation/wifi_80211/
  domain/models.py                                                  (WifiCaptureContract)
  domain/support_matrix.py                                          (P0/P1/P2 status matrix)
  domain/frame_types.py                                             (management/control/data subtype names)
  infrastructure/capture_adapter.py                                 (chunked IQ reading)
  infrastructure/legacy_ofdm_decoder.py                             (STF periodicity candidate search, §4.1)
  infrastructure/mac_parser.py                                      (RecoveredPsdu, parse_mpdu, SSID extraction, §4.3)
  infrastructure/gr_ieee80211_worker.py                              (subprocess boundary)
  application/wifi_decode_service.py                                (orchestrator, default_worker_command)
backend/app/infrastructure/web/controllers/demodulation_controller.py (all four entry points, channel lists)
backend/app/infrastructure/web/api/routes/demodulation_routes.py     (routes)
backend/app/infrastructure/jobs/job_tracker.py                       (generic job registry)
backend/app/tests/unit/test_wifi_80211_v2.py                         (unit tests)
frontend/src/presentation/views/ModulatedSignalAnalysisView.tsx      (Capture Lab button)
frontend/src/presentation/views/DemodulationView.tsx                 (Dataset Demodulation + Live Demodulation)
frontend/src/presentation/views/WifiDashboardView.tsx                (dedicated Wi-Fi Dashboard)
frontend/src/app/modules/wifi-dashboard/module.tsx                   (route registration)
frontend/src/app/services/ApiService.ts                              (job + channels + output endpoints)
```
