# BLE Lab dashboard — technical README

## 1. Purpose

BLE Lab presents independent USRP B200 radio evidence, Windows/Bleak observations, and explicit comparisons between both sources. A MAC address is not treated as proof of physical identity.

## 2. Current status

| Capability | Status |
|---|---|
| B200 hardware detection | passed |
| B200 CH37 IQ capture | passed |
| Burst detection and IQ segmentation | passed |
| BLE OTA decoding | implemented_pending_validation |
| Real CRC-valid CH37 packets | passed |
| Windows advertising | implemented |
| Windows GATT diagnostics | implemented_pending_validation |
| Deterministic native/SDR comparison | passed |
| SensorTag native/SDR match | blocked |
| RF fingerprinting | not_started |

The first hybrid match is passed for a controlled active Microsoft advertiser. SensorTag hybrid correlation remains blocked pending current transmissions.

## 3. Architecture

```text
USRP B200 -> capture worker -> SigMF -> burst detector -> existing Gate 2A.2 DSP
           -> existing Gate 1A CRC decoder -> Gate 1B semantic parser -> BLE API -> dashboard

Windows adapter -> Bleak/WinRT -> native registry -> GATT diagnostics -> BLE API -> dashboard

CRC-valid SDR packets + native advertisements -> deterministic address/payload comparison -> unified table
```

The SDR and native stores remain independent. Correlation does not overwrite either source.

## 4. Components and responsibilities

| Component | File | Responsibility | Persistent output | Limitation |
|---|---|---|---|---|
| Capture worker | `backend/tools/ble_sdr_capture_worker.py` | Fixed-channel IQ capture, SigMF, hashes, receiver events, energy segmentation | session `sdr/` directory | Power is dBFS, not calibrated dBm |
| Burst batch adapter | `backend/tools/ble_decode_burst_directory.py` | Feeds preserved IQ segments to the existing decoder | `decoded/` and per-burst directories | Offline processing |
| OTA bridge | `backend/tools/ble_gate2a2_offline_worker.py` | Existing DSP, CRC decoder and semantic parser boundary | candidates, confirmed and semantic JSONL | DSP front end remains experimental |
| Native manager | `backend/app/infrastructure/ble/native/ble_native_job_manager.py` | Scan, serialized GATT access and attempts | native registry JSON | Runtime validation pending |
| Dashboard | `BleLabView.tsx` | Capture controls, native devices and CRC-valid packet table | none | No screenshot automation |

## 5. Hardware configuration

| Field | Current CH37 value |
|---|---|
| USRP | B200 `E3R04Z1B2` |
| UHD | 4.8.0.0-release |
| USB | 2.0 |
| Antenna | RX2 |
| Sample rate | 4 MS/s |
| Frequency | 2402 MHz |
| RF bandwidth | 2 MHz |
| Gain | fixed 20 dB; AGC disabled |
| Format | `cf32_le` |
| Clock/time | UHD defaults; not externally disciplined |

Channel, duration, antenna, gain, bandwidth and format are capture-request fields. The OTA baseline is temporarily fixed to LE 1M at 4 MS/s.

## 6. DSP chain

| Stage | State | Implementation | Error/debug evidence |
|---|---|---|---|
| Noise/energy detection | passed | capture worker robust block-power threshold | `burst_candidates.jsonl` |
| Burst segmentation | passed | margin-preserving raw IQ copy | `iq_bursts/*` |
| DC removal/filtering | experimental | existing Gate 2A.2 receiver | `dsp_stage_events.jsonl`, hashes |
| CFO/timing/GFSK | implemented_pending_validation | discriminator and 16-phase timing bank | candidates/rejections JSONL |
| Preamble/AA | passed on real packets | Gate 1A decoder, AA `8E89BED6` | confirmed packets |
| Dewhitening/PDU/CRC-24 | passed on real packets | existing Gate 1A decoder | received/computed CRC |
| AD parsing | passed on real packets | existing Gate 1B parser | semantic packets |

Only CRC-valid outputs are displayed as confirmed BLE packets.

## 7. Data contracts

- Capture request: channel/frequency/sample rate/bandwidth/gain/antenna/format/duration; hardware-derived fields are never inferred.
- Capture manifest: `ble-sdr-capture-manifest-v1`; sample counts, discontinuities and SHA-256 are required.
- Burst candidate: sample interval, relative power/noise/threshold, segment path and hash. It is not a packet.
- Decoded packet: source, channel, AA, PDU, address, payload, received/computed CRC and nullable power/SNR/name.
- Native observation: normalized Bleak fields; raw HCI PDU is unavailable.
- GATT diagnostic: `ble-gatt-diagnostics-v1`; absent WinRT codes are `null`.
- Comparison: `MATCHED_BY_BOTH` requires compatible address and manufacturer payload. Partial evidence is `AMBIGUOUS`; otherwise `B200_ONLY` or `NATIVE_ONLY`.

## 8. Dashboard APIs

| Method/path | Purpose | Backend | Frontend |
|---|---|---|---|
| `GET /api/ble/capture/devices` | B200 capability | capture routes | `captureCapabilities` |
| `POST /api/ble/capture/jobs` | real IQ capture | capture routes | `createCapture` |
| `POST /api/ble/capture/recordings/{id}/analyze` | offline decoder job | capture routes | `analyzeCapture` |
| `GET /api/ble/gate2a2/jobs/{id}/confirmed-packets` | CRC-valid output | gate2a2 routes | confirmed table |
| `GET /api/ble/native/devices` | native observations | native routes | native table/comparison |
| `GET /api/ble/native/devices/{id}/gatt-diagnostics` | versioned attempts | native routes | diagnostics view |

The GATT endpoint response remains pending runtime HTTP validation.

## 9. Persistence

Real sessions are under `backend/app/infrastructure/persistence/storage/ble_lab/sessions/<session>/sdr/`. IQ is immutable SigMF data; manifests and reports are JSON; events/candidates/packets are JSONL. Segment and capture hashes support replay. New attempts append; confirmed packets never include CRC-invalid candidates.

## 10. Interface flow

- **Capture Real IQ:** starts the worker and writes SigMF plus quality evidence.
- **Start Native Scan:** starts Bleak scanning; observations persist in the native registry.
- **Inspect/Connect GATT:** serializes connection/discovery and records exact attempts.
- **Analyze/Decode:** runs the existing offline DSP/CRC/parser chain.
- **Correlate:** the confirmed table compares address and manufacturer payload with current native records.
- **Export:** job bundles are exposed by the Gate 2A.2 bundle endpoint. A dedicated unified export is pending.

## 11. Troubleshooting

| Symptom | Verify | Relevant evidence | Resolution |
|---|---|---|---|
| B200 absent | `uhd_find_devices` and runtime PATH | probe stderr | expose radioconda `Library/bin` |
| USB/overflow | manifest counts | receiver events/quality report | reduce telemetry/load; reject discontinuous data |
| No bursts | noise/threshold/power | burst candidates | check frequency, antenna, gain and transmitter |
| `burst_too_long` | segment size and configured ceiling | rejections JSONL | bounded `maximum_burst_samples`; do not bypass CRC |
| Sync/AA absent | timing/CFO candidate | candidates/rejections | inspect signal level and channel |
| CRC invalid | received vs computed CRC | decoder artifacts | keep diagnostic only |
| Windows advertising but GATT fails | failure classification | native registry/diagnostics | inspect unreachable/cache/pairing/access status |
| Dashboard empty | backend/API response | browser/backend logs | verify flags, backend and selected job |

## 12. Manual reproduction

Commands executed successfully from `backend`:

```powershell
$env:PATH='C:\Users\Usuario\radioconda\Library\bin;C:\Users\Usuario\radioconda;'+$env:PATH
C:\Users\Usuario\radioconda\Library\bin\uhd_find_devices.exe
C:\Users\Usuario\radioconda\python.exe tools\ble_sdr_capture_worker.py capture --request tmp_b200_ch37_request.json --output-dir app\infrastructure\persistence\storage\ble_lab\sessions\B200-CH37-SENSORTAG-01\sdr
C:\Users\Usuario\radioconda\python.exe tools\ble_decode_burst_directory.py --segments-dir app\infrastructure\persistence\storage\ble_lab\sessions\B200-CH37-SENSORTAG-01\sdr\iq_bursts --output-dir app\infrastructure\persistence\storage\ble_lab\sessions\B200-CH37-SENSORTAG-01\sdr\decoded --worker-repository C:\Users\Usuario\ble-worker-lab --channel 37
```

From `frontend`, `node_modules/.bin/tsc.cmd --noEmit` is validated. Full Vite build and Python pytest remain pending because the managed environment rejected unsandboxed dependency/build execution.

## 13. Experimental evidence

| Session | Samples | Losses | Bursts | CRC-valid | Addresses/result |
|---|---:|---:|---:|---:|---|
| B200-CH37-VALIDATION-02 | 4,000,000 | 0 | 20 | 19 | two Microsoft private advertisers; B200-only |
| B200-CH37-SENSORTAG-01 | 12,000,000 | 0 | 70 | 55 | `0C:1E:B4:DB:96:97` (28), `24:B7:D3:8A:32:CA` (27); B200-only |
| BLE-HYBRID-CH37-02 | 120,000,000 | 8 overflows | 668 | 17 in decoded initial subset | 671 native callbacks; 2 `MATCHED_BY_BOTH_STRONG` |

Validation-02 SHA-256: `c933b5aa0647c5a4c5b1a340f00f1453dbd1e916086a2cd90d8e23f38d10d491`. Hybrid session `BLE-HYBRID-CH37-02` demonstrated simultaneous WinRT/B200 reception. Its first strict match used address `2D:40:D0:63:C3:05`, exact Microsoft manufacturer payload, a 250 ms window and Δt `33.639 ms`. This is a logical packet correlation, not physical identity.

## 14. Change history

### 2026-07-17 — commit `4f9a32c`

- Change: persistent native diagnostics, real B200 capture/segmentation, bounded OTA burst length, batch decoding, CRC-only table and conservative comparison.
- Reason: deliver a visible real-IQ-to-packet path without a parallel decoder.
- Validation: real B200 captures, SHA verification, 74 earlier CRC-valid packets, 17 decoded packets in the hybrid subset, 2 strict hybrid matches, real API response, `py_compile`, `tsc --noEmit`, `git diff --check` (final rerun required).
- Compatibility: existing Gate 1A/1B decoder/parser reused; no fingerprint model changes.
- Rollback: revert the files listed in the delivery; stored evidence is independent and must not be deleted implicitly.

## 15. Design decisions

- Fixed CH37 avoids receiver hopping gaps and is implemented first because it is the primary baseline.
- AGC is disabled to preserve repeatable amplitude conditions.
- Power is dBFS because absolute calibration is absent.
- CRC-valid packets remain separate from energy/synchronized/decoded candidates.
- Native and SDR evidence remain independent; MAC alone is not physical identity.
- Fingerprinting starts only after stable OTA decoding to avoid learning receiver/decoder failures.

## 16. Known limitations

- Only CH37 has reproducible captures and real CRC-valid OTA packets.
- CH38/CH39 are pending.
- Current real packets are Microsoft manufacturer advertisements, not the two requested SensorTag addresses.
- A simultaneous native match is demonstrated for a Microsoft advertiser; SensorTag matches remain pending.
- The 30-second hybrid capture contains 8 overflows and is excluded from fingerprint training.
- Only the first 20 of 668 hybrid bursts have completed offline decoding; the complete batch remains pending because the current decoder is CPU-expensive.
- Native GATT diagnostics remain pending runtime validation.
- Packet UTC and calibrated power/SNR are not yet propagated to the table.
- Physical-device fingerprinting is not validated.

## 17. Next objective

Repeat the passed hybrid procedure with `B0:B4:48:C0:36:06` while it is actively advertising and produce `MATCHED_BY_BOTH_STRONG` or `MATCHED_BY_BOTH_PAYLOAD`.
## Propósito científico de las campañas híbridas

El controlador principal y UC-02 comparten `campaignPolicy.ts` y envían el
mismo contrato al backend:

- `positive_target_validation`: bloqueada salvo que el objetivo figure como
  `Visto ahora` en el escaneo nativo actual.
- `negative_control`: exige objetivo, condición negativa declarada y
  confirmación física del operador antes de iniciar.
- `exploratory_target_search`: admite objetivos históricos, pero el resultado
  no se etiqueta automáticamente como positivo ni como negativo.

Los estados `B200_ONLY` conservan `target_relation: UNKNOWN` en Dataset Studio.
Sólo un diseño experimental con identidad justificable puede asignar
`NEGATIVE_FOR_TARGET`. Si una sesión contiene pérdidas sin intervalos exactos,
todos sus ejemplos reciben `QUARANTINED_SESSION_LOSS`.

## Telemetría operacional transversal

Las operaciones largas publican progreso mediante `operationTelemetry.ts` sin
escribir en la ruta DSP. El indicador global muestra operación, fase,
porcentaje, tiempo transcurrido, tiempo restante cuando puede estimarse,
objetivo IoT, duración configurada y contadores procesado/total. La captura B200
calcula el porcentaje con muestras recibidas frente a
`duration_seconds × sample_rate_sps`; la campaña híbrida pondera captura,
decoder y correlación; Dataset Studio informa lectura, clasificación, datasheet
y hashes. Si no existe una estimación honesta, se omite el ETA.

En `BLE-EVIDENCE-DS01`, cada captura prevista dura 30 segundos. `Generar
ejemplos` no captura nuevamente el SensorTag: transforma una sesión híbrida
terminada.

## Control negativo declarado

El resultado del control y el nivel E0–E5 se presentan por separado.
`PASSED_SINGLE_RUN` significa cero atribuciones al objetivo durante una única
ejecución con condición física confirmada por el operador. No implica una tasa
estadística de falsos positivos. Dataset Studio conserva E1/E2 y utiliza
`NEGATIVE_BY_EXPERIMENTAL_CONTRACT`; esta etiqueta no identifica al transmisor
ambiental. Si hubo pérdidas, todos esos ejemplos siguen en
`QUARANTINED_SESSION_LOSS`. El control reforzado permanece pendiente hasta
obtener una referencia positiva E3 de otro dispositivo y una captura limpia.

## Lectura correcta de Dataset Studio

La interfaz separa condiciones ejecutadas, conformes al protocolo y aceptadas.
Las sesiones históricas de 3 s no cuentan como conformes al protocolo congelado
de 30 s, y los valores `documentar` se presentan como metadatos incompletos.
La matriz separa ejecución, evidencia observada, calidad, conformidad y
aceptación. Un E4 observado no implica aceptación para entrenamiento.

Las dos tasas de correlación muestran numerador y denominador. La cuarentena
local sólo se declara con intervalos exactos auditables. El split muestra por
separado la comprobación estructural de fuga y la preparación científica; con
cero ejemplos aceptados se presenta como `No preparado`.
