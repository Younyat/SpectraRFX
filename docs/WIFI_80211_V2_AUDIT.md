> **Superseded.** This audit predates the validated V3 worker integration
> (real, FCS-confirmed frame recovery, live-capture routing, and the Wi-Fi
> Dashboard). It is kept for historical reference only — for the current,
> accurate state of Wi-Fi decoding see
> [`docs/technical-readmes/wifi_80211/README.md`](technical-readmes/wifi_80211/README.md).

# IEEE 802.11 decoder V2 audit and implementation status

## Safety and evidence boundary

This is a passive decoder for authorized laboratory captures. It provides no
injection, deauthentication, credential recovery, or decryption. A protected
MPDU exposes only visible PHY/MAC metadata; its body is labelled
`protected_ciphertext`.

`WIFI_DEMOD_V2=true` enables the Dataset V2 foundation. With the flag absent or
false, `wifi_80211` continues to use the existing activity scaffold. V2 does
not yet satisfy P0: a pinned, licensed and validated `gr-ieee802-11` worker is
still required for L-LTF/L-SIG/DATA recovery and PCAPNG/Radiotap export.

## Audited data paths

| Path | Current finding |
|---|---|
| `DemodulationView.tsx` | Live mode sends M1/M2 start/stop to marker-band capture. Dataset mode sends the stored IQ path and capture metadata. Artifact downloads use the existing result-output endpoint. |
| `ApiService.ts` | Marker-band and Dataset requests use existing endpoints; no PSD, Max Hold, waterfall, or PNG is sent as decoder input. |
| `DemodulationResult` / local `DecodedPacket` | Results are extensible but packet typing is BLE-centric. V2 artifacts remain represented through `outputs` until professional Wi-Fi frame types are added. |
| `demodulation_controller.py` | Dataset IQ was silently limited to 2,000,000 complex samples by `_read_complex_iq`. V2 branches before that load and streams the complete file. The monolithic Wi-Fi scaffold detects energy bursts only. |
| `demodulation_pipeline.py` | Generic analog DSP pipeline; it is not an IEEE 802.11 PHY decoder and is unchanged. |
| Immediate live capture | `capture_marker_band_iq.py` writes interleaved complex float32 IQ and metadata. M1/M2 filtering can be applied before the selected IQ artifact is decoded; an unfiltered artifact may also be retained. |
| Trigger/pre-trigger | Marker capture supports energy-triggered slicing. `triggered_burst_capture.py` provides the corrected chronological circular buffer. Wi-Fi STF triggering and the recommended 200 us pre-trigger are not yet integrated. |
| Dataset/SigMF | SigMF reads `core:sample_rate`, `core:datatype`, and first-capture `core:frequency`. Dataset records supply SDR/capture fields when present. |
| GNU Radio/UHD worker | Current capture workers use GNU Radio/UHD. No pinned `gr-ieee802-11` version/commit is installed or invoked by V2 yet. |
| Artifacts | Existing paths write `decoded_packets.json` and `demodulation_report.json`. V2 foundation writes `capture_manifest.json`, `decoded_frames.json`, `failed_frame_candidates.json`, and `demodulation_report.json`. Remaining professional exports are pending. |

## Capture semantics observed

| Field | Finding |
|---|---|
| Datatypes | `cf32_le`, `ci16_le`, and `cu8` are accepted. |
| I/Q order | Interleaved I then Q. `cf32_le` is two little-endian float32 values per complex sample; `ci16_le` is normalized by 32768; `cu8` is centered at 127.5. |
| Sample rate | Taken from confirmed capture metadata/request or SigMF `core:sample_rate`; V2 records original rate and processes the corresponding sample count. |
| Hardware/signal center | The old contract had one `center_frequency_hz`. V2 separates hardware and channel center, falling back to the old value for compatibility. |
| First-sample timestamp | Optional in current records. Absence is retained as unknown; V2 does not invent an absolute timestamp. |
| Gaps/overflows | Fingerprinting metadata has overflow counters, but older captures may not. V2 records unknown rather than assuming continuity. |
| Gain/antenna/device/serial | Propagated when present; otherwise explicitly null. |
| DC/IQ correction | Not established by the old Dataset contract. V2 defaults both to false and records the decision. |
| Filter | V2 records a filter definition. Dataset default is raw IQ/no filter; live marker capture may have filtered before storage. |
| Samples read | Legacy Dataset path reads at most 2,000,000 by default. V2 uses bounded chunks, absolute indexes, overlap and EOF detection, and separately reports `samples_total_in_file`, `samples_read_from_file`, `unique_samples_processed`, `overlap_samples_reprocessed`, `samples_discarded`, `trailing_incomplete_bytes`, and `analysis_truncated`. |
| Display offset | `noiseFloorOffset` is never included or applied. Metrics are native digital-sample quantities/dBFS-related values, not dBm. |

## Support matrix

- P0 legacy OFDM 802.11a/g: external worker required; STF candidate search is
  implemented only as the first evidence level.
- P1 DSSS/CCK 802.11b: not implemented and kept as an independent mode.
- P2 HT/VHT/HE: identification not implemented; payload decoding is not
  promised.

A channel-width/frequency match is displayed as **Wi-Fi channel-profile
match**, not confirmed Wi-Fi. STF correlation candidates remain failed
candidates until synchronization, valid L-SIG, complete PSDU, valid FCS, and a
parseable MAC frame are demonstrated.

## Validation completed in this foundation

- Chunked `cf32_le` reading preserves every sample and absolute order.
- A file larger than 2,000,000 samples is processed completely without silent
  truncation.
- STF periodicity requires a documented plateau and zero input produces no
  candidate.
- Protected MPDU parsing never exposes the body as clear payload.
- Existing pre-trigger wrap-around regression tests remain passing.

## Required before claiming P0

Pin and validate `gr-ieee802-11` plus GNU Radio/UHD versions; implement and
verify channelization to exactly 20 MS/s, L-LTF/L-SIG/DATA decoding, all legacy
rates, soft Viterbi/descrambling, MAC/IE parsing, FCS, PCAPNG/Radiotap, job
progress, deterministic vectors, reference loopback/impairment curves, and a
controlled OTA capture. Also run the complete backend suite once its Python
environment includes the declared dependencies, and regress every existing
pipeline and capture path.

## Reference environment preflight

RadioConda currently provides GNU Radio `3.10.12.0`, but its packaged OOT
modules are different revisions from the P0 pins:

- `gnuradio-ieee802_11 ...+g761bdd9` (required pin starts `ad0598e`);
- `gnuradio-foo ...+g9e0e2` (required pin starts `4c2a471`).

Compiling the packaged `wifi_loopback.grc` with `grcc` generated
`wifi_phy_hier.py` but rejected the loopback as an invalid flowgraph with four
unconnected ports. Therefore reference loopback, PSDU equality, L-SIG, FCS and
legacy-rate evidence are **not passed**. The installed packages must not be
used to claim the pinned P0 result.
