# BLE capture module technical README

Audience: programmers maintaining the BLE-RFFI acquisition path.

This README is part of the project audit trail. Any meaningful change to this
module must update this file in the same work item: what changed, why it
changed, what scientific assumption it protects, and how it was verified.

## Module scope

This module owns the experimental USRP B200 IQ acquisition path used by the
BLE-RFFI stage-one workflow:

- SDR discovery and capability reporting.
- Capture request validation.
- Out-of-process execution of `backend/tools/ble_sdr_capture_worker.py`.
- Capture manifests, quality reports, live telemetry and terminal status.
- Qualification-only captures that prove acquisition stability before any BLE
  campaign capture is allowed.

It does not validate BLE demodulation, target identity, E4 ground truth,
dataset eligibility, or model training. Those remain separate gates.

## Main files

- `ble_capture_job_manager.py`: API-facing job manager, request validation,
  protocol-field augmentation, hash verification and capture listing.
- `ble_iq_capture_service.py`: subprocess boundary and RadioConda runtime
  environment for SoapySDR/UHD.
- `ble_sdr_device_service.py`: SDR probe and B200 device identity handling.
- `ble_capture_routes.py`: FastAPI routes for devices, jobs, live frames and
  metadata.
- `backend/tools/ble_sdr_capture_worker.py`: real acquisition worker. It is
  deliberately outside the FastAPI process.

## Scientific constraints

The platform must not confuse a file with the right size with a scientifically
valid acquisition. A capture is not acceptable for later BLE-RFFI evidence if
any of these conditions fail:

- expected samples equal actual samples;
- expected file size equals actual file size;
- `overflow_count == 0`;
- `input_discontinuities == 0`;
- `short_read_count == 0`;
- `write_error_count == 0`;
- `writer_queue_overrun_count == 0`;
- `hash_status == VERIFIED`;
- `metadata_status == COMPLETE`.

Qualification captures are technical evidence only:

```text
execution_purpose = ACQUISITION_QUALIFICATION
scientific_campaign_member = false
dataset_eligible = false
qualification_only = true
```

They must not count as positives, negatives, campaign conditions, Dataset
Studio material, or training readiness.

## Acquisition and persistence design

The critical acquisition sequence is:

```text
UHD receive
-> preallocated buffer
-> bounded queue
-> dedicated writer
-> file close
-> size verification
-> post-capture hash
-> terminal manifest
```

The UHD receive loop must not wait for:

- disk writes;
- SHA-256 calculation;
- frontend/live JSON serialization;
- large manifest writes;
- BLE decoding;
- correlation;
- dataset/example generation.

Telemetry is allowed only when explicitly enabled. With
`ui_polling_mode = disabled`, the worker must not write `live.json` from the
critical loop.

## Format fields

Each diagnostic or qualification capture records the three distinct format
layers:

```text
cpu_format
otw_format
file_format
bytes_per_cpu_sample
bytes_per_wire_sample
bytes_per_file_sample
conversion_enabled
```

This prevents a clean `ci16_le` run from being misread as proof that only disk
size changed. It may also change USB payload, host copies, memory pressure, or
conversion behavior, depending on the SDR driver path.

Current protocol remains:

```text
protocol_sample_format = cf32_le
protocol_revision = qualification-rev1 / actual campaign revision
```

Do not silently switch the campaign to `ci16_le`. If `ci16_le` is ever adopted,
create a new protocol revision, new preprocessing contract, new qualification
profile, and rerun all qualification gates.

## Writer instrumentation

Terminal manifests and quality reports must include writer and host metrics:

```text
writer_thread_mode
writer_queue_capacity_bytes
writer_queue_high_watermark_bytes
writer_queue_overrun_count
maximum_buffer_occupancy
write_block_size_bytes
write_call_count
mean_write_latency_ms
maximum_write_latency_ms
measured_write_throughput_bytes_s
memory_copy_count_per_block
storage_target
storage_free_bytes
hash_during_capture
manifest_during_capture
fsync_during_capture
cpu_usage_mean
cpu_usage_max
process_cpu_usage_mean
memory_usage_max
```

If a loss occurs, record the most specific supported correlation:

```text
writer_queue_full
write_latency_spike
buffer_exhaustion
host_receive_overrun
unknown
```

Do not invent a root cause when the instrumentation cannot isolate it.

## USB3 diagnostic history

Earlier B200-only qualification attempts under the old path produced correct
file sizes but overflows/discontinuities. After moving the B200 to USB3 and
instrumenting the writer, the controlled diagnostic matrix was repeated.

Valid matrix after disabling live writes in the critical loop:

| Run group | Profile | Result |
|---|---|---|
| B1-B3 | `cf32_le`, no persistence | 40,000,000 samples, zero losses |
| C1-C3 | `cf32_le`, persistence, 320,000,000 bytes | zero losses, hash verified |
| E1-E3 | `ci16_le`, persistence, 160,000,000 bytes | zero losses, hash verified |

Interpretation:

```text
ACQUISITION_DIAGNOSTIC = COMPLETED
CF32_PERSISTENCE_DIAGNOSTIC_PASSED = true
ROOT_CAUSE_PRIOR_LOSSES = NOT_FULLY_ISOLATED
```

The prior losses must not be attributed to one single cause because USB mode,
writer design, instrumentation, and live telemetry behavior changed during the
same stabilization cycle.

## Acquisition qualification result

After the diagnostic matrix, three consecutive B200-only qualification
captures were executed with the scientific profile:

```text
sample_format = cf32_le
sample_rate_sps = 4000000
duration_seconds = 10
center_frequency_hz = 2402000000
bandwidth_hz = 2000000
antenna = RX2
gain_db = 20
usb_mode = USB 3
expected_samples = 40000000
expected_file_size_bytes = 320000000
```

All three passed:

| Capture | Samples | File size | Losses | Hash |
|---|---:|---:|---|---|
| `BLE-IQ-ACQQUAL-Q1-af246b260971` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | VERIFIED |
| `BLE-IQ-ACQQUAL-Q2-6e85a5ccc574` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | VERIFIED |
| `BLE-IQ-ACQQUAL-Q3-e3b8f324c709` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | VERIFIED |

Intermediate gate interpretation immediately after B200-only qualification:

```text
ACQUISITION_QUALIFICATION = PASSED_3_CONSECUTIVE
HYBRID_CONCURRENCY_QUALIFICATION = UNLOCKED_NEXT_ONLY
S001-POS = BLOCKED
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
```

At that intermediate point only the hybrid concurrency qualification was
unlocked. The current state after hybrid qualification is documented below.

## Hybrid concurrency qualification result

After the B200-only qualification passed, three Windows-BLE-plus-B200
qualification captures were executed. These runs test only whether the Windows
BLE scanner and the USRP B200 acquisition path can run concurrently for the
same 10-second qualification profile without introducing B200 sample loss.

They do not verify SensorTag identity, E4 ground truth, CRC validity,
Windows-B200 correlation, dataset eligibility, or model readiness.

Frozen acceptance threshold:

```text
minimum_rf_concurrency_overlap_seconds = 9.0
minimum_rf_concurrency_overlap_fraction = 0.90
```

The original dashboard value `concurrency_overlap_seconds = 17.00` was a
legacy job-interval overlap and included non-RF work such as setup, closing,
hashing or manifest handling. It is not a valid RF overlap metric because a
10-second acquisition cannot have more than 10 seconds of RF concurrency.

The corrected metric separates:

```text
b200_job_started_at
b200_job_finished_at
b200_rf_started_at
b200_rf_finished_at
windows_scan_started_at
windows_scan_finished_at
```

For future runs, `b200_rf_started_at` and `b200_rf_finished_at` are emitted by
the SDR worker around the sample reception interval. For the three existing
hybrid runs, the previous worker did not record the exact first-sample
timestamp. The RF overlap is therefore reconstructed from sample count and the
recorded scan envelope: Windows scanning started before the recorded B200 job
interval and finished after it, so the 10-second RF interval is fully covered
even though the exact first-sample timestamp was not present in the old
artifacts.

Corrected invariants:

```text
b200_rf_duration_seconds = actual_samples / sample_rate_sps = 10.0
0 <= rf_concurrency_overlap_seconds <= 10.0
0 <= rf_concurrency_overlap_fraction <= 1.0
```

All three hybrid runs pass the corrected RF-overlap gate:

| Capture | Scan session | Samples | File size | Losses | Overlap | Windows callbacks / unique |
|---|---|---:|---:|---|---:|---:|
| `BLE-IQ-HYBQUAL-H1-6d97ec1435eb` (`HCQ1`) | `BLE-HYBRID-QUAL-H1-6d97ec1435eb` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 10.00 s / 1.00 | 743 / 57 |
| `BLE-IQ-HYBQUAL-H2-f77ffff0ceb5` (`HCQ2`) | `BLE-HYBRID-QUAL-H2-f77ffff0ceb5` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 10.00 s / 1.00 | 687 / 55 |
| `BLE-IQ-HYBQUAL-H3-e86f90fa5ab6` (`HCQ3`) | `BLE-HYBRID-QUAL-H3-e86f90fa5ab6` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 10.00 s / 1.00 | 628 / 55 |

`HCQ1`, `HCQ2`, and `HCQ3` are aliases for the qualification runs only. The
old artifact identifiers are preserved. Future technical hybrid qualification
runs must use `HCQ*` naming because `H1`--`H3` are reserved for confirmatory
scientific hypotheses in the paper.

Windows callback count and unique observations are diagnostics of scanner
activity only. They are not target identity evidence, are not E4 evidence, and
must not be used to unlock a negative control.

Current gate interpretation:

```text
HYBRID_CONCURRENCY_QUALIFICATION = PASSED_3_CONSECUTIVE
qualification_profile_matches_campaign = true
S001-POS = UNLOCKED_NEXT_ONLY
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
```

The negative control remains blocked until a later S001-POS run is accepted
and eligible. These hybrid qualification runs remain `qualification_only`,
`scientific_campaign_member = false`, and `dataset_eligible = false`.

This profile qualifies only the 10-second engineering qualification profile:

```text
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S
```

The 120-second confirmatory campaign described in the paper is a different
experimental profile. It requires a new `qualification_profile_id` and a full
new acquisition plus hybrid concurrency requalification before it can be used
for scientific campaign captures.

## Estado cientifico y tecnico actual

El objetivo final del modulo no es obtener una accuracy alta ni entrenar un
clasificador aislado. El objetivo es construir una cadena BLE-RFFI trazable
que permita evaluar, dentro de un alcance declarado, si una emision BLE
capturada por el USRP B200 es compatible con la unidad fisica enrolada o con
la poblacion alternativa evaluada.

La cadena prevista es:

```text
unidad fisica registrada
-> protocolo congelado
-> receptor cualificado
-> concurrencia Windows BLE-B200 cualificada
-> ground truth valido
-> capturas positivas aceptadas
-> controles negativos aceptados
-> dataset trazable
-> splits sin fuga
-> entrenamiento
-> calibracion y umbral congelados
-> validacion independiente
-> decision con posibilidad de abstencion
-> trazabilidad hasta el I/Q original
-> despliegue controlado en Live Monitor
```

El modelo final debe usar solo informacion derivada del I/Q del B200. Windows
BLE se usa para observacion logica, ground truth, asociacion temporal y
etiquetado. No puede ser entrada del modelo: direccion BLE, `local_name`,
GATT, payload, manufacturer data ni identidad reportada por Windows.

Estado actual:

```text
ACQUISITION_DIAGNOSTIC = COMPLETED
ACQUISITION_QUALIFICATION = PASSED_3_CONSECUTIVE
HYBRID_CONCURRENCY_QUALIFICATION = PASSED_3_CONSECUTIVE
qualification_profile_matches_campaign = true

qualification_profile_id =
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S

receiver_serial = E3R04Z1B2
usb_mode = USB_3
center_frequency_hz = 2402000000
sample_rate_sps = 4000000
analog_bandwidth_hz = 2000000
cpu_format = cf32
file_format = cf32_le
antenna = RX2
gain_db = 20
duration_seconds = 10
disk_persistence_enabled = true

Etapa actual = PREPARATION_FOR_POSITIVE_PILOT
CURRENT_STAGE = PREPARATION_FOR_POSITIVE_PILOT
NEXT_OPERATOR_ACTION = PREPARE_AND_EXECUTE_S001_POS
NEXT_HARDWARE_ACTION = POSITIVE_PILOT_ONLY
Siguiente ejecucion de hardware = C001 / S001-POS
execution_purpose = POSITIVE_PILOT
S001-POS = UNLOCKED_NEXT_ONLY
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
LIVE_MODEL = BLOCKED
Campana de 120 s = NOT_QUALIFIED
ROOT_CAUSE_PRIOR_LOSSES = NOT_FULLY_ISOLATED
```

Se ha demostrado solo para el perfil anterior que el B200 puede adquirir 10 s
de I/Q por USB 3, persistir `cf32_le` con 40,000,000 muestras y 320,000,000
bytes, cerrar sin overflows, discontinuidades, short reads, write errors ni
queue overruns, verificar hashes, completar manifiestos y funcionar
concurrentemente con Windows BLE con `rf_concurrency_overlap_seconds = 10.0`
y `rf_concurrency_overlap_fraction = 1.0`.

Estas cualificaciones no demuestran identidad del SensorTag, ground truth E4,
fingerprinting valido, separacion target-background, dataset valido, modelo
entrenable, rendimiento temporal, generalizacion, capturas estables de 120 s
ni comparacion entre unidades del mismo modelo.

### Objetivo de la siguiente etapa

La positiva piloto `C001 / S001-POS` debe demostrar conjuntamente:

- la unidad fisica correcta fue seleccionada;
- el operador confirmo la preparacion fisica;
- Windows BLE observo el objetivo;
- el preflight seguia vigente al iniciar la captura;
- el B200 realizo una adquisicion limpia;
- el decoder obtuvo paquetes CRC validos;
- la asociacion Windows-B200 produjo evidencia suficiente;
- la identidad del objetivo no quedo ambigua;
- los artefactos quedaron integros;
- la sesion puede considerarse elegible para dataset.

La positiva separa observacion minima E4 de aceptacion cientifica para
dataset:

```text
E4_MINIMAL_OBSERVED =
unique_target_crc_packets_with_strong_association >= 1

E4_ACCEPTED_FOR_DATASET =
unique_strong_only_target_crc_packets >= K_campaign
y todos los demas gates de identidad, calidad e integridad aprobados

minimum_unique_target_packets_for_e4_observation = 1
minimum_unique_target_packets_for_dataset_acceptance = 3
quality_gate_version = ble-rffi-positive-pilot-gate-v2
```

Tres paquetes unicos CRC validos con asociacion fuerte no conflictiva
constituyen un minimo de redundancia para esta prueba piloto de 10 s. Este
umbral es un criterio de ingenieria del piloto, no una estimacion estadistica
de suficiencia general. No se reutiliza automaticamente para capturas de
120 s, campanas same-model, paper definitivo, otras tasas de advertising,
otras duraciones ni otros canales.

Antes de iniciar hardware para `S001-POS`, el backend congela y registra el
contrato exacto de ejecucion. Esta congelacion ocurre antes de crear la sesion
activa y antes de arrancar Windows BLE o el B200. El manifiesto debe contener:

```text
source_repository_commit
source_working_tree_status
source_working_tree_dirty
source_working_tree_diff_sha256
protocol_manifest
protocol_manifest_sha256
protocol_hash
protocol_frozen_at_utc
execution_freeze
quality_gate_version = ble-rffi-positive-pilot-gate-v2
qualification_profile_id =
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S
```

Si el arbol de trabajo no esta limpio, no se oculta: se registra
`source_working_tree_status = DIRTY_RECORDED` y se guarda el hash del diff
tracked. Esto no sustituye a un commit limpio para publicacion definitiva,
pero evita que una ejecucion piloto quede sin trazabilidad tecnica.

Para `execution_purpose = POSITIVE_PILOT`, el backend rechaza cambios criticos
con `REQUALIFICATION_REQUIRED` si no coinciden canal 37, 10 s, ganancia 20 dB,
`quality_gate_version` o el `qualification_profile_id` cualificado. No se debe
corregir manualmente un manifiesto despues de observar resultados.

La interfaz de esta etapa debe funcionar como un asistente numerado para un
operador sin conocimientos de BLE, SDR, RFFI, ground truth o procesamiento
I/Q. Cada paso muestra:

```text
1. que esta comprobando la plataforma;
2. que debe hacer fisicamente el usuario;
3. que resultado se espera;
4. que significa un fallo;
5. cual es la unica accion disponible.
```

El asistente indica explicitamente cuando no debe encenderse el SensorTag,
cuando debe colocarse, cuando debe encenderse, cuando debe esperar el preflight
Windows BLE, cuando se inicia la captura de 10 s y cuando la plataforma esta
procesando. Las fases futuras (`S001-NEG`, dataset, entrenamiento y live model)
permanecen bloqueadas y explican por que. Despues de cualquier captura el flujo
se detiene, muestra un resumen humano y conserva los detalles tecnicos
expandibles; ninguna transicion cientifica ocurre automaticamente.

No debe usarse el numero bruto de correlaciones fuertes como numero de
paquetes. Un paquete con una asociacion fuerte y otra asociacion competidora
incompatible no se considera strong-only para el gate cientifico. El resumen
debe distinguir:

```text
windows_target_observations
detected_bursts
decoded_packets
total_crc_valid_packets
unique_crc_valid_packets
target_crc_valid_packets
environmental_crc_valid_packets
unattributed_crc_valid_packets
target_strong_correlation_edges
target_ambiguous_correlation_edges
unique_target_crc_packets_with_strong_association
unique_strong_only_target_crc_packets
unique_target_crc_packets_with_ambiguous_association
unique_target_crc_packets_with_conflicting_association
target_association_conflict_count
```

Estados esperados:

```text
Un solo paquete fuerte:
maximum_observed_evidence_level = E4
association_evidence_status = MINIMAL_OBSERVATION
ground_truth_status = INSUFFICIENT_FOR_ACCEPTED_E4
dataset_eligibility_status = NOT_ELIGIBLE
reason_code = INSUFFICIENT_UNIQUE_TARGET_PACKETS

Tres o mas paquetes strong-only y todos los gates aprobados:
maximum_observed_evidence_level = E4
association_evidence_status = ACCEPTED
ground_truth_status = PASSED_E4
dataset_eligibility_status = ELIGIBLE

Caso ambiguo:
maximum_observed_evidence_level = E4
association_evidence_status = AMBIGUOUS
ground_truth_status = INSUFFICIENT_FOR_ACCEPTED_E4
dataset_eligibility_status = NOT_ELIGIBLE
reason_code = TARGET_ASSOCIATION_AMBIGUOUS
```

La identidad reportada por Windows es ground truth auxiliar, no entrada del
modelo. Una positiva fallida nunca se convierte en negativa. Solo una
positiva aceptada y elegible desbloquea `S001-NEG = UNLOCKED_NEXT_ONLY`;
dataset y entrenamiento siguen bloqueados.

### Intento S001-POS fallido por continuidad RF

El intento `BLE-HYBRID-20260724T101703Z-7493e2` / `BLE-IQ-16cde3ef4a33`
congelo correctamente el protocolo positivo piloto:

```text
freeze_validation_status = PASSED
execution_purpose = POSITIVE_PILOT
condition_id = C001
session_id = S001-POS
physical_unit_id = CC2650-UNIT-01
quality_gate_version = ble-rffi-positive-pilot-gate-v2
qualification_profile_id =
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S
```

El archivo I/Q alcanzo el tamano esperado, pero la adquisicion no es
cientificamente valida:

```text
actual_samples = 40000000
actual_file_size_bytes = 320000000
hash_status = VERIFIED
metadata_status = COMPLETE
manifest_status = COMPLETE
overflow_count = 1
discontinuity_count = 1
failure_reason_codes =
  ACQUISITION_OVERFLOW
  ACQUISITION_DISCONTINUITY
```

El primer evento fue `host_receive_overrun` en
`sample_index_start = 1070667`, aproximadamente `0.268 s` despues del inicio
RF a 4 MS/s. Los contadores del escritor no apoyan una atribucion al disco en
ese intento:

```text
writer_queue_overrun_count = 0
writer_error = null
maximum_write_latency_ms ~= 2.5
writer_queue_high_watermark_bytes = 1600000
writer_queue_capacity_bytes = 67108864
```

Por tanto, el resultado se conserva como intento historico fallido y no
elegible. No desbloquea negativa, dataset ni entrenamiento.

Durante la revision se detecto una incongruencia de propagacion: el protocolo
congelado declaraba `frontend_preview_enabled = false`, pero la peticion real
al capturador heredaba el valor por defecto `frontend_preview_enabled = true`
y `ui_polling_mode = normal`. El orquestador debe pasar siempre estos campos
desde la metadata congelada hacia el worker de captura. Para S001-POS, la
peticion efectiva debe mantener:

```text
frontend_preview_enabled = false
ui_polling_mode = minimal
online_decoder_enabled = false
online_correlation_enabled = false
```

El intento positivo piloto no es una cualificacion tecnica. Aunque sea
fallido y no elegible, su clasificacion documental debe ser:

```text
execution_purpose = POSITIVE_PILOT
scientific_campaign_member = true
dataset_eligible = false
qualification_only = false
scientific_corpus_membership = positive_pilot_pending_gate
```

### Intento S001-POS limpio pero sin evidencia B200

El intento `BLE-HYBRID-20260724T104524Z-8b70f0` / `BLE-IQ-f25ccce7d158`
cerro correctamente la adquisicion y el procesamiento, pero quedo en
cuarentena cientifica:

```text
terminal_status = COMPLETED
acquisition_quality_status = PASSED
signal_quality_status = PASSED
artifact_integrity_status = VERIFIED
protocol_conformance_status = PASSED
metadata_status = COMPLETE

windows_target_observations = 56
candidate_bursts = 0
detected_bursts = 0
total_crc_valid_packets = 0
target_crc_valid_packets = 0
unique_strong_only_target_crc_packets = 0
target_result = TARGET_NATIVE_ONLY
ground_truth_status = INSUFFICIENT_FOR_ACCEPTED_E4
dataset_eligibility_status = NOT_ELIGIBLE
```

Este resultado significa que Windows BLE observo el objetivo durante la
ventana de campana, pero la cadena B200 `detector -> decoder -> CRC` no
produjo evidencia RF decodificable en CH37. No es una asociacion ambigua,
porque no existen paquetes B200 que asociar. Los codigos correctos para este
caso son:

```text
ZERO_BURST_CANDIDATES
ZERO_CRC_VALID_PACKETS
TARGET_NATIVE_ONLY_B200_NOT_CORROBORATED
EVIDENCE_BELOW_ACCEPTED_E4
```

No debe desbloquearse `S001-NEG`, dataset ni entrenamiento. Antes de repetir
una positiva como intento cientifico, conviene revisar la visibilidad RF del
objetivo para el B200: antena RX2 conectada, posicion/orientacion/distancia,
ganancia, presencia de energia alrededor de 2402 MHz, sensibilidad del
detector de rafagas y alineacion del decoder offline con la forma de onda
capturada. Si se cambia un parametro critico del perfil cualificado, debe
declararse `REQUALIFICATION_REQUIRED`.

Revision posterior: el worker de captura solo ejecuta `detect_bursts(...)`
cuando la peticion contiene `analysis_enabled = true`. Los intentos positivos
que conservaron 40,000,000 muestras pero terminaron con
`ZERO_BURST_CANDIDATES` deben revisarse teniendo en cuenta si la deteccion
offline estaba habilitada. Si `analysis_enabled = false`, el resultado
significa que no se generaron segmentos para el decoder; no demuestra por si
solo ausencia de energia BLE en el I/Q ni fallo de visibilidad RF.

Para `execution_purpose = POSITIVE_PILOT`, el contrato congelado debe incluir:

```text
analysis_enabled = true
frontend_preview_enabled = false
online_decoder_enabled = false
online_correlation_enabled = false
```

`analysis_enabled` activa la deteccion y segmentacion offline despues de
cerrar y verificar el archivo I/Q. No habilita decoder ni correlacion online
durante la adquisicion critica.

Incidencia corregida el 2026-07-24: algunas rutas de UI podian iniciar
`S001-POS` sin propagar `analysis_enabled` dentro de `experimental_metadata`,
lo que hacia fallar el congelado con
`PROTOCOL_FREEZE_MISMATCH:analysis_enabled` antes de usar hardware. La decision
tecnica fue normalizar `analysis_enabled = true` en dos capas:

```text
frontend startHybrid payload normalizer
backend _freeze_positive_pilot_protocol
```

La razon cientifica es que `analysis_enabled` no es un metadato editable ni una
opcion del operador para `POSITIVE_PILOT`; es parte del contrato congelado que
separa adquisicion critica de deteccion offline. La adquisicion sigue usando
`frontend_preview_enabled = false`, `online_decoder_enabled = false` y
`online_correlation_enabled = false`.

Un dry-run sin modificar artefactos sobre `BLE-IQ-e8edc49b59a0` con la misma
regla energetica del worker encontro eventos candidatos:

```text
noise_power_dbfs ~= -66.90
threshold_dbfs ~= -60.88
active_blocks = 58534
candidate_groups = 8047
```

Por tanto, el siguiente paso preferente no es repetir hardware, sino ejecutar
una reanalisis offline trazable del I/Q ya capturado o repetir S001-POS solo
despues de congelar y commitear `analysis_enabled = true`.

### Diagnostico RF recepcion-vs-deteccion

El modulo incorpora un diagnostico offline independiente de campana para
capturas preservadas:

```text
GET /api/ble/capture/recordings/{capture_id}/rf-diagnostic
GET /api/ble/capture/rf-diagnostic-profiles
```

El diagnostico no escribe sobre la captura original y devuelve:

```text
actual_samples
actual_file_size_bytes
data_sha256 / metadata_sha256
hash_status
mean_power_dbfs
maximum_block_power_dbfs
noise_floor_dbfs
clipping_percent
psd.points alrededor de center_frequency_hz
energy_time_series
energy_excursion_count
threshold_dbfs
candidate_count
candidate_preview antes del decoder
diagnostic_conclusion.layer
```

La conclusion separa dos capas:

```text
CANDIDATES_AVAILABLE_FOR_DECODER_REPLAY
  Hay energia/candidatos en el I/Q preservado. No repita hardware a ciegas:
  ejecute replay detector/decoder y ajuste la segmentacion si procede.

DETECTION_REPLAY_REQUIRED
  Hay energia pero no candidatos segun la regla evaluada. Corrija detector
  mediante replay, sin modificar el I/Q original.

RF_VISIBILITY_REVIEW_REQUIRED
  No hay energia candidata. Revise antena, RX2, sintonia, ganancia, driver y
  flujo de muestras antes de repetir S001-POS.
```

El perfil `RFVIS-CH37-RX2-4M8M-BW4M-GAIN-SWEEP-v1` permite pruebas
diagnosticas fuera de campana con 2402 MHz, RX2, 4/8 MS/s, 4 MHz de
bandwidth y barrido de ganancia. Estas ejecuciones deben quedar marcadas como:

```text
execution_purpose = RF_VISIBILITY_DIAGNOSTIC
scientific_campaign_member = false
dataset_eligible = false
qualification_only = true
does_not_replace_qualification = true
```

Usar un resultado diagnostico para cambiar la campana cientifica requiere una
revision explicita del perfil y recualificacion completa.

### Replay offline detector/decoder trazable

Antes de repetir `S001-POS`, ejecutar `S001-NEG`, generar dataset o entrenar,
el flujo exige cerrar el replay offline de la captura preservada que ya mostro
energia candidata. La primera captura bajo este contrato es:

```text
source_execution_id = BLE-HYBRID-20260724T104524Z-8b70f0
source_capture_id = BLE-IQ-f25ccce7d158
source_iq_sha256 = df5fd832fa1a05027b6782d5e2f5734377ea9de08fca168a465aefc0e195c9ba
analysis_configuration_id = ble-rffi-offline-detector-decoder-replay-v1
```

Endpoints:

```text
POST /api/ble/capture/recordings/{capture_id}/offline-replay
GET  /api/ble/capture/recordings/{capture_id}/offline-replay/latest

POST /api/ble/capture/recordings/{capture_id}/offline-replay-jobs
GET  /api/ble/capture/recordings/{capture_id}/offline-replay-jobs/latest
GET  /api/ble/capture/recordings/{capture_id}/offline-replay-jobs/{replay_run_id}
POST /api/ble/capture/recordings/{capture_id}/offline-replay-jobs/{replay_run_id}/cancel
```

El replay no selecciona la ultima sesion global. Primero resuelve una unica
fuente de verdad `execution_id -> capture_id -> iq_sha256`. Rechaza la
ejecucion cuando el `capture_id` no pertenece al `execution_id`, el SHA-256 no
coincide, faltan metadatos criticos o la configuracion RF no es:

```text
sample_format = cf32_le
sample_rate_sps = 4000000
center_frequency_hz = 2402000000
bandwidth_hz = 2000000
ble_channel = 37
```

Cada ejecucion crea un directorio nuevo bajo:

```text
BLE-IQ-*/offline_replays/{replay_run_id}
```

y preserva:

```text
replay_manifest.json
replay_configuration.json
replay_summary.json
candidate_funnel.json
candidate_rejection_summary.json
crc_valid_packets.jsonl
target_association_results.json
worker_stdout.log
worker_stderr.log
input_iq_sha256.txt
```

Los replays largos deben ejecutarse mediante `offline-replay-jobs`. El endpoint
sin sufijo `-jobs` se conserva por compatibilidad, pero bloquea la peticion HTTP
hasta terminar o alcanzar timeout. El job escribe `job.json` y expone
`decoded/progress.json` como progreso operativo:

```text
state
replay_run_id
progress.processed_segments
progress.total_segments
progress.crc_valid_packets
progress_percent
cancel_supported
```

La cancelacion de un job nuevo termina el proceso decoder, conserva los
artefactos parciales y registra `CANCELLED_PARTIAL`. Un replay sincronico
heredado puede mostrarse como `legacy_sync_run`, pero no puede cancelarse desde
el nuevo job porque el proceso no fue creado con el callback de cancelacion.

El operador no debe encender ni apagar el SensorTag durante un replay offline.
No hay nueva captura B200 ni nuevo escaneo Windows BLE; solo se reanalizan el
I/Q, los metadatos y las observaciones Windows ya preservados.

La razon cientifica es separar capas:

```text
energia RF presente
-> regiones candidatas pre-decoder
-> intentos GFSK/decoder
-> paquetes CRC validos
-> asociacion Windows preservada en la ventana original
-> elegibilidad de la sesion fuente
```

Las regiones energeticas no se denominan paquetes BLE hasta que exista
estructura BLE y CRC valido. Si el decoder actual no expone internamente
subcontadores de timing, preambulo o Access Address, el embudo informa
`NOT_INSTRUMENTED_BY_CURRENT_DECODER` en vez de inventar ceros.

Semantica de analisis no ejecutado:

```text
analysis_execution_status = NOT_EXECUTED
burst_candidate_count = null
crc_valid_packet_count = null
burst_detection_status = NOT_EVALUATED
crc_validation_status = NOT_EVALUATED
```

No se emiten `ZERO_BURST_CANDIDATES` ni `ZERO_CRC_VALID_PACKETS` salvo que la
etapa correspondiente se haya ejecutado completamente y devuelto realmente
cero.

Mientras no exista replay terminado:

```text
stage = OFFLINE_DETECTOR_DECODER_REPLAY_REQUIRED
next_operator_action = RUN_OFFLINE_DETECTOR_DECODER_REPLAY
S001_POS = BLOCKED_PENDING_REPLAY
S001_NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
```

### Replay resumable por lotes con checkpoint (2026-07-24)

El primer intento de replay sobre `BLE-IQ-e8edc49b59a0` (8,047 candidatos)
demostro que un unico intento sincrono con un solo timeout global
(`COMPLETED_PARTIAL_TIMEOUT`, 932/8,047 procesados) no es una base cientifica
cerrable: cada reintento volvia a decodificar desde el candidato 0, perdiendo
el trabajo previo, y un segmento lento podia bloquear miles de segmentos
posteriores. `ble_offline_replay.py` se reescribio para eliminar ambos
problemas sin tocar el repositorio externo `ble-worker-lab` (no frozen, fuera
de este repo): solo se orquesta `backend/tools/ble_decode_burst_directory.py`,
que ya soportaba `--start-index/--end-index` sobre segmentos pre-detectados.

Identidad de candidato determinista, independiente del orden de la lista:

```text
candidate_id = sha256(source_iq_sha256 : start_sample : end_sample : analysis_configuration_id)[:24]
```

Cada replay persiste `candidate_manifest.jsonl` (un `candidate_id` por fila,
`processing_status` en `PENDING|PROCESSED|FAILED_TIMEOUT|FAILED_DECODER_ERROR`,
`attempt_count`, `processing_duration_ms`, `decoder_result`, `crc_status`,
`rejection_reason`) y `replay_state.json` (identidad congelada del run:
`source_iq_sha256`, `analysis_configuration_id`, `worker_version`,
`decoder_version`, `candidate_manifest_sha256`, contadores de timeout/error/
reinicio, `checkpoint_sequence`, `last_checkpoint_at`). `processed_candidate_ids`,
`pending_candidate_ids` y `failed_candidate_ids` no se duplican como listas
aparte: se derivan siempre de `candidate_manifest.jsonl`, que es la unica
fuente de verdad, para evitar que un contador y una lista puedan desincronizarse.

Motor de decodificacion por lotes con aislamiento ante un candidato lento:

```text
1. Se agrupan hasta batch_size candidatos PENDING contiguos.
2. Se invoca el decoder existente sobre ese rango, acotado por batch_timeout_seconds.
3. Si el lote termina completo: se marca PROCESSED cada candidato y se hace checkpoint.
4. Si el lote se interrumpe (timeout o crash): los candidatos ya completados
   dentro del lote quedan PROCESSED (checkpoint inmediato); el candidato en
   curso se reintenta EN SOLITARIO, acotado por per_candidate_timeout_seconds.
5. Si el candidato aislado tampoco termina: FAILED_TIMEOUT (o
   FAILED_DECODER_ERROR si el proceso salio con codigo != 0). El resto del
   backlog continua sin esperarlo.
```

Tres timeouts independientes, todos configurables por payload o variable de
entorno (`BLE_RFFI_REPLAY_BATCH_SIZE`, `BLE_RFFI_REPLAY_BATCH_TIMEOUT_SECONDS`,
`BLE_RFFI_REPLAY_PER_CANDIDATE_TIMEOUT_SECONDS`,
`BLE_RFFI_OFFLINE_REPLAY_TIMEOUT_SECONDS` para `job_time_budget_seconds`):
`per_candidate_timeout` acota un candidato aislado, `batch_timeout` acota un
lote completo, `job_time_budget` acota cuanto puede correr una sola llamada
`POST .../offline-replay-jobs` antes de checkpointear y devolver control al
operador. Ningun timeout intenta procesar los 8,047 candidatos en una sola
espera de horas.

Reanudacion: `POST .../offline-replay-jobs` con `replay_run_id` en el cuerpo
continua el mismo directorio en vez de crear uno nuevo. Antes de continuar se
revalida que no cambiaron `source_iq_sha256`, `analysis_configuration_id`,
`worker_version`, `decoder_version` ni `candidate_manifest_sha256`; si alguno
cambio, se rechaza con `REPLAY_RESUME_CONFIGURATION_CHANGED:<campo>` en vez de
continuar en silencio sobre un contexto distinto. Solo los candidatos
`PENDING` se reprocesan; `PROCESSED`/`FAILED_*` nunca se repiten, por lo que
"parcial + varias reanudaciones" produce el mismo `candidate_manifest.jsonl`
final (mismo `crc_status`/`decoder_result` por candidato) que un unico intento
corrido de una sola vez con presupuesto suficiente. Cada paquete CRC valido
lleva ademas un `packet_id = sha256(candidate_id : packet_start_sample :
payload_hex)` para trazabilidad estable independiente del reintento que lo
produjo.

Cancelacion ordenada: el `cancel_requested` callback se revisa entre lotes y
dentro del poll del subproceso activo; al detectarse, el lote/candidato en
curso se termina (SIGTERM, luego SIGKILL tras 5 s), lo ya decodificado se
conserva, se hace un checkpoint final y el job termina en
`CANCELLED_WITH_CHECKPOINT` con `resume_available=true`. La cancelacion nunca
se reporta como resultado cientifico negativo.

Separacion de estados cientifico vs de ejecucion en `replay_summary.json`:

```text
execution_status = PARTIAL | FULLY_PROCESSED | COMPLETED_WITH_FAILED_SEGMENTS | CANCELLED_WITH_CHECKPOINT | FAILED
termination_reason = NONE | JOB_TIME_BUDGET_EXCEEDED | OPERATOR_CANCELLED | SOURCE_OR_WORKER_ERROR
scientific_completion_status = COMPLETE | INCOMPLETE   (COMPLETE solo si pending_segments == 0)
decision_scope = FULL_CAPTURE | PROCESSED_SUBSET_ONLY
resume_available = bool
coverage = {total_candidate_segments, processed_segments, failed_segments, pending_segments, coverage_percentage, checkpoint_sequence, last_checkpoint_at}
```

Mientras `scientific_completion_status = INCOMPLETE`, `decision.decision` nunca
puede ser `E4_ACCEPTED_FOR_DATASET_CANDIDATE` (se degrada a
`E4_CANDIDATE_REQUIRES_COMPLETE_REPLAY`) y `dataset_eligibility_status` queda
forzado a `NOT_ELIGIBLE`, con `DECODER_REPLAY_INCOMPLETE` en `reason_codes`.
El dashboard (`OfflineReplayStep`) refleja lo mismo: mientras el replay este
incompleto, la etapa `replay` del asistente no avanza a `positive`/`dataset`
aunque exista un `replay_summary.json` parcial, y solo se habilita
`[CONTINUAR DESDE CHECKPOINT]`.

Asociacion Windows-B200 por paquete: `target_association_results.
packet_association_ledger` guarda, por cada paquete CRC valido, su
`candidate_id`, `pdu_type`/`tx_add`/`rx_add` (del PDU decodificado),
`advertiser_address_canonical`, el callback Windows mas cercano dentro de
±250 ms si existe, `time_delta_ms`, y una razon explicita de no-asociacion
(`ADDRESS_NOT_PRESENT_IN_PDU`, `ADDRESS_MISMATCH`,
`MULTIPLE_NATIVE_CALLBACKS`, `TIME_DELTA_ABOVE_THRESHOLD`,
`WINDOWS_TIMESTAMP_UNAVAILABLE`) en vez de solo un contador agregado. No se
ajustaron umbrales de asociacion para forzar coincidencias; el motor de
comparacion de direcciones sigue siendo canonico-contra-canonico (ver
`address_parser.py` en `ble-worker-lab`: `address_canonical` ya invierte el
orden on-air, por lo que `ADDRESS_BYTE_ORDER_MISMATCH` no es una causa
plausible en este pipeline salvo error de captura).

Limite conocido y declarado, no oculto: el decoder existente (`ble_worker.
dsp_receiver.run_offline_receiver`) solo expone eventos de etapa agregados
por ejecucion (`format_validation`, `burst_detection`, `bitstream_recovery`,
`existing_gate1a_decoder`, `existing_gate1b_parser`), no subcontadores por
candidato de timing, preambulo, Access Address, header o dewhitening. El
embudo sigue informando `NOT_INSTRUMENTED_BY_CURRENT_DECODER` para esos
campos en vez de inventar ceros; exponerlos exigiria instrumentar
`ble-worker-lab`, que es un repositorio externo no congelado y esta
deliberadamente fuera del alcance de este cambio.

Pruebas: `backend/app/tests/unit/test_ble_offline_replay_resumable.py` cubre,
contra un decoder falso (`backend/app/tests/unit/fixtures/
fake_ble_decode_worker.py`) que respeta el mismo contrato CLI que el decoder
real: reanudacion sin reprocesar candidatos `PROCESSED`, equivalencia entre
"parcial + reanudacion" y un intento corrido de una sola vez, ausencia de
`packet_id` duplicados, rechazo de reanudacion cuando cambia
`source_iq_sha256` o `analysis_configuration_id`, un candidato lento que no
bloquea el resto del lote (`FAILED_TIMEOUT` aislado), cancelacion ordenada con
checkpoint y reanudacion posterior, y que `pending_segments > 0` fuerza
`dataset_eligibility_status = NOT_ELIGIBLE` y `scientific_decision =
INCOMPLETE_REPLAY`.

### Migracion de runs pre-checkpoint y correcciones criticas de dispatch (2026-07-24)

Al intentar reanudar el replay real `BLE-RFFI-REPLAY-20260724T161348Z-74cac1`
(932/8,047 procesados, creado antes de que existiera el motor de checkpoint)
contra el backend en ejecucion, la verificacion en vivo -- no solo pytest --
encontro tres fallos reales que no habian aparecido en las pruebas unitarias
porque estas llamaban a `BleOfflineReplayService.create()` directamente y se
saltaban la capa `BleCaptureJobManager`/HTTP:

```text
1. Migracion de runs legacy.
   El run real no tenia replay_state.json ni candidate_manifest.jsonl (solo
   existian antes de este trabajo). _resume() ahora hace bootstrap en el
   mismo directorio a partir de burst_candidates.jsonl y
   decoded/batch_summary.json cuando falta el checkpoint, en vez de exigirlo
   o de perder el progreso ya decodificado. BleCaptureJobManager.
   start_offline_replay() se actualizo para aceptar tambien estos runs
   legacy (antes exigia replay_state.json y rechazaba con
   OFFLINE_REPLAY_JOB_NOT_FOUND).

2. Bug critico de despacho fresh-vs-resume.
   BleCaptureJobManager siempre inyecta replay_run_id en el payload que pasa
   a BleOfflineReplayService.create() -- tanto para un run nuevo (ID recien
   generado, para poder escribir job.json antes de lanzar el hilo) como para
   una reanudacion real. El _run() anterior interpretaba "replay_run_id
   presente" como "debe reanudar", así que CUALQUIER replay nuevo lanzado a
   traves del job manager (es decir, el boton normal del dashboard) entraba
   por error a _resume() sobre un directorio vacio y fallaba con
   REPLAY_RUN_NOT_FOUND. Nunca se detecto en las pruebas porque estas
   llamaban al servicio sin pasar por el job manager. La logica correcta -- y
   ya corregida -- decide fresh vs resume por si el directorio ya tiene
   progreso real en disco (replay_state.json o burst_candidates.jsonl), no
   por si el llamador paso un ID.

3. Bug de resultado obsoleto en el estado del job.
   offline_replay_job() fusionaba replay_summary.json en la respuesta y
   sobrescribia el estado "queued"/"running" a "completed" en cuanto ese
   archivo existiera en disco, sin comprobar si pertenecia al intento EN
   CURSO o a un intento anterior sobre el mismo replay_run_id. Al reanudar,
   el resultado antiguo (pre-reanudacion) se mostraba de inmediato como si el
   nuevo intento ya hubiera terminado. Corregido: el resultado en disco solo
   se adjunta cuando job.json ya alcanzo un estado terminal escrito por el
   propio hilo en ejecucion.
```

Verificacion: ademas de las pruebas nuevas
(`test_ble_offline_replay_job_manager.py`, que reproduce ambos bugs con un
`BleCaptureJobManager` real y un decoder falso), se ejecuto la reanudacion
real contra el backend en ejecucion (`POST .../offline-replay-jobs` con el
`replay_run_id` real) y se confirmo progreso genuino y creciente en
`candidate_manifest.jsonl`/`replay_state.json` bajo
`BLE-IQ-e8edc49b59a0/offline_replays/BLE-RFFI-REPLAY-20260724T161348Z-74cac1/`.
Sin esta verificacion en vivo, el bug de despacho (punto 2) habria roto el
boton "Ejecutar replay detector/decoder" para cualquier ejecucion nueva desde
el dashboard, no solo para reanudaciones.

Nombres de campo exactos anadidos a `coverage`/`candidate_funnel`/
`replay_final_report.json` para separar "intentado" de "decodificado con
exito":

```text
successfully_processed_segments
failed_timeout_segments
failed_decoder_error_segments
pending_segments
attempted_coverage = (successful + failed) / total
successful_coverage = successful / total
```

`replay_final_report.json` es el informe obligatorio de cierre: incluye estas
coberturas, CRC validos/unicos, candidatos de direccion objetivo, coincidencias
fuertes/conflictivas, un resumen de razones de no-asociacion
(`association_rejection_summary`, agregado desde `packet_association_ledger`),
la calidad de adquisicion de la fuente y la decision cientifica. Mientras
`pending_segments > 0` incluye `scope_note` explicando que el informe cubre
solo el subconjunto procesado, no la captura completa.

## Verification commands

Compile the worker with the same Python runtime used for SoapySDR/UHD:

```powershell
C:\Users\Usuario\radioconda\python.exe -m py_compile backend/tools/ble_sdr_capture_worker.py
```

Probe the B200 with the RadioConda environment:

```powershell
$runtime='C:\Users\Usuario\radioconda'
$env:PATH=($runtime+'\Library\bin')+';'+($runtime+'\Scripts')+';'+$runtime+';'+(Join-Path $env:SystemRoot 'System32')
$env:SOAPY_SDR_PLUGIN_PATH=$runtime+'\Library\lib\SoapySDR\modules0.8'
& "$runtime\python.exe" backend/tools/ble_sdr_capture_worker.py devices
```

Expected B200 evidence includes serial `E3R04Z1B2` and UHD stderr text
containing `Operating over USB 3`.

## Developer rule for future changes

When modifying this module, update this README with:

- the technical change;
- the scientific reason;
- the gate or status affected;
- the artifact IDs or tests used for verification;
- any limitation or claim boundary that remains.

This prevents future work from relying on memory, chat history, or ambiguous
dashboard state.
