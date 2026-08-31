# BLE-RFFI Dataset Spec v1

Versión 1, 2026-07-31. Documenta las 3 capas del dataset BLE-RFFI **tal como ya existen en el código**,
señala explícitamente qué campos de la especificación completa de rediseño todavía no existen, y cita las
lecciones ya extraídas de la auditoría de datasets externos (`README_INSPECCION_DATASETS_ORACLE.md`,
`C:\Users\Usuario\Desktop\NICS\datasets\rf oracle\`) en vez de repetir ese análisis.

Este documento es deliberadamente corto: es la Fase 4 del documento de rediseño completo del operador,
adaptada a lo que el pipeline real ya hace — no una reescritura del sistema.

## Las 3 capas, ya implementadas

### 1. RAW — `CaptureRecord`

Fichero: `contracts/capture.py`. Persistencia: `legacy_capture_root/<capture_id>/`
(`captures/<capture_id>.json` + el IQ real `.sigmf-data`-equivalente).

Inmutable tras crearse: `delete_legacy_capture()` es la única operación destructiva, y es explícita
(irreversible, borra el IQ real de disco). Ya incluye: `iq_sha256`, `sample_rate_sps`, `center_frequency_hz`,
`ble_channel`, `gain_db`, `receiver_device_id`/`sdr_serial`, `capture_duration_s`, `created_at_utc`,
`capture_purpose`/`target_state`/`isolation_declared_physical_unit_id`/`target_reference_id` (condición
declarada por el operador), `acquisition_quality`.

### 2. CURATED — `ExampleRecord` + `ExampleAnnotation`

Fichero: `contracts/example.py`. Persistencia: `evidence/<capture_id>/examples.jsonl` +
`annotations.jsonl`. Construida por `evidence/evidence_stage.py` a partir del replay OFFLINE_REPLAY
(decodificación real BLE, Gate 2A.2).

Ya conserva la cadena `captura → ráfaga (candidate_id) → paquete (packet_id) → ejemplo (example_id)`:
`example_id` se deriva de `source_iq_sha256 + iq_start_sample + iq_end_sample + candidate_id + packet_id`
(`ExampleRecord.make_example_id`) — nunca del label, para que un cambio de etiqueta nunca invente un
ejemplo nuevo. Tres ejes ya separados explícitamente (nunca conflados en un solo campo):
`association_status` (`STRONG`/`AMBIGUOUS`/`NONE`/`CONFLICT`/`PHYSICAL_ISOLATION_DECLARED`),
`quality_status` (CRC), `dataset_eligibility` (`ELIGIBLE`/`QUARANTINED`/`PENDING_ANALYSIS`/`INELIGIBLE`).

### 3. FROZEN — `DatasetManifest` + `SplitManifest`

Ficheros: `contracts/` (dataset/split), `dataset/dataset_builder.py`, `quality/split_builder.py`.

`DatasetManifest.frozen` es de una sola dirección: una vez con `dataset_manifest_sha256`, cualquier cambio
exige una `dataset_version` nueva (`derived_from` registra el padre), nunca una edición. Ya incluye:
`example_ids` exacto, `dataset_manifest_sha256`, `captures`/`sessions`/`physical_units`, `creation_policy`.
`SplitManifest` ya es session-disjoint (`leakage_check`) y separa TRAIN/VALIDATION/TEST con
`split_manifest_sha256` propio.

## Qué pide la Fase 4 completa que TODAVÍA no existe (huecos reales, no trabajo ya hecho)

- **SNR por captura**, **clipping**, **CFO estimado** persistidos en `CaptureRecord`/`ExampleRecord` — hoy
  no se calculan ni se guardan.
- **PHY declarado** (`LE_1M`/`LE_2M`/`LE_CODED_S2`/`LE_CODED_S8`) — el decoder Gate 2A.2 asume LE 1M
  (legacy advertising); no hay campo para declarar/verificar el PHY por captura.
- **Canal BLE como variable de dominio explícita en el split** — hoy `ble_channel` se guarda en
  `CaptureRecord`, pero `SplitBuilder` no lo usa para estratificar ni para bloquear generalización
  cross-canal. Confirmado en el diagnóstico de 2026-07-31
  (`BLE_RFFI_IDENTITY_DIAGNOSTIC_2026-07-31.md`): el dataset de identidad real disponible hoy es
  100% canal 37, cero variación.
- **Calibración del receptor por frecuencia** (ganancia efectiva, ancho de banda efectivo, tiempo de
  calentamiento, temperatura) — no persistido hoy.
- **Estados científicos de cobertura de canal** (`SINGLE_CHANNEL_ONLY`,
  `CROSS_CHANNEL_GENERALIZATION_SUPPORTED`, etc.) — no existen como campo; hoy solo se ve la advertencia
  genérica "un solo canal" en `dataset_composition_report()`.
- **Ablation study de sample rate/ancho de banda (A0/A1/A2)** — no se ha ejecutado; el pipeline solo ha
  usado el perfil actual (4 MS/s, 2 MHz).

## Lecciones ya extraídas de la auditoría externa, aplicadas aquí (sin repetir el análisis)

De `README_INSPECCION_DATASETS_ORACLE.md` (auditoría ya hecha sobre KRI/ORACLE, UAV Lightbridge,
IEEE/CBRS, WiFi-Dataset):

- **Nunca confiar en el dtype declarado sin verificar el tamaño real.** KRI declara `cf32` pero el tamaño
  de archivo implica `complex128` — el mismo tipo de inconsistencia que ya se vigila en BLE-RFFI Studio
  vía `hash_status: VERIFIED` y comprobación de `actual_samples`/`actual_size_bytes` contra lo declarado.
- **La unidad de independencia estadística nunca puede ser la ventana/paquete cuando vienen del mismo
  archivo.** Ya aplicado: `SplitBuilder` particiona por sesión, no por paquete ni por ventana — y el
  diagnóstico de 2026-07-31 confirma que aun así, con muy pocas sesiones por clase, el problema persiste
  (menos sesiones que grupos de validación fiables, no un fallo del propio splitting por grupo).
- **No declarar una tarea de identidad si no hay variación real de identidades físicas.** El bloque
  IEEE/CBRS externo tiene transmisores/receptor constantes — la auditoría correctamente rechaza usarlo
  como "device fingerprinting". Aplicado en BLE-RFFI Studio: `SAME_MODEL_UNIT_IDENTIFICATION` solo se
  intenta cuando hay 2+ `physical_unit_id` distintos con 3+ sesiones cada uno (`explain_feasibility`).
- **Una métrica de validación alta con split aleatorio de ventanas no demuestra fingerprinting robusto** —
  exactamente el patrón que el diagnóstico de 2026-07-31 reprodujo con datos reales BLE: 1.0 de accuracy en
  TRAIN, colapso a recall 0.0 en VALIDATION para las clases con menos sesiones, en 4 arquitecturas
  distintas.

## Próximo paso

Este spec no reemplaza el diagnóstico — lo acompaña. Las prioridades concretas de captura/campaña que se
derivan del resultado real están en `BLE_RFFI_IDENTITY_DIAGNOSTIC_2026-07-31.md` (más sesiones balanceadas,
orden intercalado, un segundo canal BLE) y son las que hay que resolver antes de invertir en
representaciones nuevas (R1-R5, TPD) o en la auditoría completa de los datasets externos de 100+GB.
