# Inspeccion BLE RFFI de spectrum-lab

Fecha de inspeccion: 2026-07-30

Alcance: inspeccion estatica y de artefactos del proyecto `spectrum-lab`, con foco en BLE, captura USRP B200, creacion de datasets, entrenamiento, evaluacion y causas probables de falsos positivos. No se modifico codigo ni datos. Este fichero es un informe nuevo y no sustituye al README principal.

## Conclusion ejecutiva

El proyecto tiene una base de ingenieria fuerte para BLE-RFFI: contratos separados para capturas, ejemplos, anotaciones, datasets, splits, entrenamientos y bundles; gates de adquisicion B200; trazabilidad por SHA-256; separacion entre `REAL_B200` y `SYNTHETIC_TEST_ONLY`; y defensas contra splits no listos, fugas por muestra/sesion y entrenamientos de una sola clase.

Pero, segun los artefactos locales inspeccionados, los modelos entrenados hasta ahora no demuestran deteccion real de identidad fisica BLE. La causa principal no es que falte una CNN mas compleja. El problema esta antes: los datasets reales disponibles no forman todavia un conjunto profesional de identificacion de dispositivo BLE con verdad-terreno fuerte, balanceado, multi-unidad, multi-sesion, multi-condicion y validado por holdout independiente.

La mayoria de modelos reales entrenados resuelven `TARGET_VS_BACKGROUND`, no `SAME_MODEL_UNIT_IDENTIFICATION`. Es decir, aprenden a separar `TARGET_DEVICE` frente a `BACKGROUND_ENVIRONMENT`, o incluso aprendieron una unica clase en runs historicos. Eso no responde la pregunta forense correcta: "esta emision BLE pertenece a esta unidad fisica concreta y no a otra unidad fisica parecida?".

## Evidencia local inspeccionada

### Documentacion BLE principal

Ficheros revisados:

- `README.md`
- `docs/technical-readmes/ble/README.md`
- `backend/app/infrastructure/ble/capture/README.md`
- `backend/app/modules/ble_rffi_studio/README.md`
- `backend/app/modules/ble_rffi_studio/scientific_basis/README.md`

Estado declarado en el README raiz:

- BLE Dataset Studio Pilot v1: 3 campanas historicas.
- Ejemplos generados: 338.
- Ejemplos incluidos: 0.
- Ejemplos en cuarentena: 338.
- Positive E4 campaign: `PASSED_SINGLE_RUN`.
- Exploratory E2 campaign: `PASSED`.
- Declared negative control: `PASSED_SINGLE_RUN`.
- Reinforced negative control: `PENDING`.
- Clean captures: `PENDING`.
- Training: `NOT_READY`.
- Fingerprinting: `NOT_VALIDATED`.

Interpretacion: el propio proyecto declara que el pipeline de fingerprinting BLE no esta validado cientificamente, aunque existan runs y bundles posteriores en el storage.

### Estado de captura BLE e IQ

Segun `backend/app/infrastructure/ble/capture/README.md`:

- La adquisicion B200 de 10 s fue cualificada: 40,000,000 muestras, `cf32_le`, 4 MS/s, 2.402 GHz, RX2, ganancia 20 dB, USB 3.
- Tres capturas B200-only pasaron sin overflow ni discontinuidades.
- Tres capturas hibridas Windows BLE + B200 pasaron concurrencia RF completa.
- Estas cualificaciones son tecnicas: no validan identidad SensorTag, ground truth E4, CRC real, asociacion Windows-B200, dataset ni modelo.
- La campana de 120 s esta `NOT_QUALIFIED`.
- `S001-NEG`, `DATASET`, `TRAINING` y `LIVE_MODEL` aparecen bloqueados en ese documento para la etapa descrita.

Segun `docs/technical-readmes/ble/physical_capture_acceptance_usrp_b200.json`:

- Captura activa aceptada para visualizacion: `BLE-IQ-18e58422f746`, 12,000,000 muestras, 96,000,000 bytes, `overflow_count=0`, `input_discontinuities=0`, hash verificado.
- Control con transmisor apagado: `BLE-IQ-8f31009519a3`, mismo tamano esperado, pero `overflow_count=7` e `input_discontinuities=7`.
- `ble_decode_attempted=false`.
- `capture_and_decode_enabled=false`.
- `gate2a2_promoted=false`.
- `iq_recovery_validated=false`.
- `ota_validated=false`.

Interpretacion: hay prueba real de adquisicion/visualizacion IQ, pero no hay prueba cerrada de recuperacion OTA BLE que permita tratar la decodificacion como base cientifica final.

### Estado Gate 2A.2, DSP e IQ recovery

Segun `docs/technical-readmes/ble/README.md`:

- Gate 1B valida bitstream replay con vectores conocidos; no toca RF/IQ.
- Gate 2A.2 DSP/IQ recovery esta en desarrollo externo (`ble-worker-lab`) y no esta congelado.
- `iq_recovery_validated=false`.
- `ota_validated=false`.
- `Receiver Candidate B=not frozen`.
- `Holdout B=not created`.
- `capture_and_decode=disabled`.
- Candidate A fallo por timing fraccional.
- Candidate B consiguio 381/384 casos en sweep de desarrollo, pero el requisito estricto era 384/384.

Interpretacion: no se debe vender ningun modelo como detector real de dispositivo BLE si la etapa que localiza/recupera paquetes sobre IQ OTA real sigue sin estar congelada y validada. Para RFFI se puede entrenar sobre ventanas IQ, pero las ventanas y etiquetas deben estar cerradas cientificamente.

## Inventario de artefactos locales

Storage inspeccionado bajo `backend/app/infrastructure/persistence/storage`:

| Area | Ficheros | Tamano aprox. | Lectura tecnica |
|---|---:|---:|---|
| `ble` | 265,301 | 20.64 GB | IQ, capturas BLE, nativo Windows, jobs Gate 2A.2. |
| `recordings` | 1,103 | 71.50 GB | Grabaciones RF generales. |
| `ble_rffi_studio` | 2,778 | 0.24 GB | Captures, evidence, datasets, splits, training_runs, bundles. |
| `ble_lab` | 2,179 | 0.19 GB | Laboratorio BLE bitstream/parser/replay. |
| `mlops` | 133 | 0.30 GB | Artefactos MLOps generales. |

Detalle relevante:

- `storage/ble`: 261,284 `.cf32`, 58 pares SigMF (`.sigmf-data`/`.sigmf-meta`), 1,887 JSON, 852 JSONL.
- `storage/ble_rffi_studio`: 2,194 JSON, 399 JSONL, 126 `.joblib`, 24 `.pt`, 32 `.md`.
- Capturas Studio: 54 reales `BLE-IQ-*.json` y 6 sinteticas.

Esto muestra volumen de datos, pero volumen no equivale a dataset valido para identidad. El problema es la calidad y estructura de la verdad-terreno.

## Contratos de datos y columnas existentes

### `CaptureRecord`

El flujo BLE-RFFI usa capturas ya existentes, no recaptura dentro del modulo Studio. Deben contener, entre otros, `capture_id`, `campaign_id`, `execution_id`, `session_id`, `data_origin`, `iq_sha256`, `sample_rate_sps`, `center_frequency_hz`, proposito de captura, unidad fisica declarada si existe, y trazabilidad al IQ.

### `ExampleRecord`

`backend/app/modules/ble_rffi_studio/contracts/example.py` separa muestra y etiqueta. Campos principales inspeccionados:

- Identidad/trazabilidad: `example_id`, `project_id`, `campaign_id`, `capture_id`, `execution_id`, `session_id`, `candidate_id`, `packet_id`.
- Ventana IQ: `source_iq_sha256`, `iq_start_sample`, `iq_end_sample`.
- Identidad fisica/logica: `physical_unit_id`, `logical_transmitter_id`.
- Contexto BLE/captura: `capture_purpose`, `background_kind`, `channel`, `sample_rate_sps`, `center_frequency_hz`.
- Calidad/asociacion: `association_status`, `quality_status`, `dataset_eligibility`.
- Procesamiento: `preprocessing_profile_id`, `created_at`.

Fortaleza: la separacion entre `ExampleRecord` y `ExampleAnnotation` reduce el riesgo de mezclar dato, etiqueta y decision.

Debilidad: faltan metadatos fisicos y BLE suficientes para controlar dominio: canal real por paquete si hay multi-canal, CFO por paquete validado, RSSI/potencia por paquete, SNR, ganancia exacta, antena, distancia, orientacion, temperatura, bateria, payload/PDU estable, version firmware, estado TX power, repeticion de campana, dia/sesion, operador, entorno RF y grado de aislamiento verificable.

### `ExampleAnnotation`

La anotacion documenta evidencia y decision. La evidencia puede venir de:

- `B200_PACKET`: paquete BLE CRC valido o invalido.
- `WINDOWS_OBSERVATION`: observacion nativa Windows cercana.
- `OPERATOR_DECLARATION`: declaracion del operador.

Hallazgo critico: cuando `isolation_declared_physical_unit_id` existe, `EvidenceStage` atribuye todos los paquetes recuperados a esa unidad por declaracion fisica, no por direccion ni por Windows. El propio codigo documenta que esto es mas debil que una asociacion fuerte.

### `DatasetManifest`

`backend/app/modules/ble_rffi_studio/contracts/dataset.py` contiene:

- `dataset_id`, `dataset_version`, `project_id`, `campaign_id`.
- `data_origin` (`REAL_B200` o `SYNTHETIC_TEST_ONLY`).
- `physical_units`, `captures`, `sessions`, `example_ids`.
- `class_distribution`, `creation_policy`, `frozen`, `dataset_manifest_sha256`.
- `derived_from`, `created_at`.

Fortaleza: manifest frozen + hashes + origen real/sintetico.

Debilidad: `ACCEPTED_FOR_TRAINING` todavia puede ser cierto para datasets que no son adecuados para una tarea concreta de identidad, por ejemplo datasets de una sola clase `UNKNOWN` o datasets TARGET_VS_BACKGROUND.

## Estado de evidencia y elegibilidad

Conteos locales agregados de evidence JSONL:

| Campo | Conteo |
|---|---:|
| `quality_status=PASSED` | 18,896 |
| `dataset_eligibility=PENDING_ANALYSIS` | 18,707 |
| `dataset_eligibility=QUARANTINED` | 189 |
| `association_status=PHYSICAL_ISOLATION_DECLARED` | 12,092 |
| `association_status=NONE` | 6,358 |
| `association_status=CONFLICT` | 189 |
| `association_status=AMBIGUOUS` | 185 |
| `association_status=STRONG` | 72 |

Interpretacion: hay muchos paquetes/ventanas que pasan CRC, pero muy pocas asociaciones fuertes. La mayor parte de la atribucion a unidad fisica depende de aislamiento declarado por el operador. Eso puede valer para pilotos controlados, pero no es una base suficiente para entrenar un detector robusto si el ambiente BLE no esta realmente limpio.

Caso local documentado de contaminacion: en `backend/app/modules/ble_rffi_studio/README.md` aparece la captura `BLE-IQ-f37b9df07274`, donde dos paquetes CRC-validos separados por 21 muestras tenian direcciones BLE distintas (`38:27:73:88:E6:A2` y `84:DD:20:F0:8D:20`) dentro de una captura atribuida por aislamiento a `keyfobdemo 01`. El gate bloqueo el entrenamiento y la solucion fue retirar la captura contaminada.

## Datasets congelados inspeccionados

| Dataset | Origen | Unidades | Capturas | Ejemplos | Distribucion | Lectura cientifica |
|---|---|---:|---:|---:|---|---|
| `BLE-RFFI-CC2650-YOUNES-ENV-DS` | REAL_B200 | 0 | 3 | 355 | `UNKNOWN=355` | No sirve para identificar unidad fisica. |
| `BLE-RFFI-PROJECT-SAME_MODEL_UNIT_IDENTIFICATION-DS` | REAL_B200 | 2 | 15 | 5,569 | `CC2650-UNIT-01=2139`, `keyfobdemo 02=1478`, `UNKNOWN=1952` | No aceptado: 728 grupos duplicados exactos. |
| `BLE-RFFI-TI_SENSOR_TAG-SAME_MODEL_UNIT_IDENTIFICATION-DS` | REAL_B200 | 0 | 1 | 529 | `UNKNOWN=529` | No hay unidades fisicas etiquetadas. |
| `BLE-RFFI-TI_SENSOR_TAG-TARGET_VS_BACKGROUND-DS` | REAL_B200 | 0 | 1 | 529 | `UNKNOWN=529` | No hay positivos reales. |
| `BLE-RFFI-TI_SENSORTAG-AUTO-DS` | REAL_B200 | 4 | 28 | 9,578 | 4 unidades + `UNKNOWN=1230` | Se uso en runs TARGET_VS_BACKGROUND, no como identidad multi-unidad cerrada. |
| `BLE-RFFI-TI_SENSORTAG-TARGET_VS_BACKGROUND-DS` | REAL_B200 | 1 | 30 | 10,052 | `keyfobdemo 01=4686`, `UNKNOWN=5366` | Dataset de presencia objetivo/fondo, no identificacion entre dispositivos. |
| `SMOKE-DS`, `SYNTHETIC_DEMO-*` | SYNTHETIC_TEST_ONLY | 2 | n/a | 72 | 2 sinteticas | Validan software, no fingerprint fisico real. |

Punto clave: el unico dataset real que parece aproximarse a same-model unit identification (`BLE-RFFI-PROJECT-SAME_MODEL_UNIT_IDENTIFICATION-DS`) esta rechazado por 728 grupos duplicados exactos. Los demas aceptados para training no prueban identidad fisica multi-dispositivo.

## Splits inspeccionados

Fortalezas del codigo en `quality/split_builder.py`:

- Divide por sesion completa, no por ventana dentro de la misma sesion.
- Comprueba fuga por `capture_id`, `execution_id`, `session_id`, `candidate_id`, `packet_id` y rango de muestra.
- Exige al menos dos clases en TRAIN.
- Para `TARGET_VS_BACKGROUND`, solo considera background valido si la captura fue declarada `BACKGROUND_TARGET_OFF` o `BACKGROUND_GENERAL`.

Hallazgos:

- `BLE-RFFI-PROJECT-PREVIEW-DS-r2yh6a` si tiene split READY para `SAME_MODEL_UNIT_IDENTIFICATION` con `CC2650-UNIT-01` y `keyfobdemo 02`, pero es preview `0.0.0`, no dataset congelado final aprobado.
- `BLE-RFFI-TI_SENSORTAG-AUTO-DS__TARGET_VS_BACKGROUND` esta READY, pero las etiquetas reales de entrenamiento son `TARGET_DEVICE` vs `BACKGROUND_ENVIRONMENT`; las unidades `CC2541SensorTag`, `CC2650-UNIT-01`, `keyfobdemo 01`, `keyfobdemo 02` quedan colapsadas como target para esa tarea.
- Los datasets con solo `UNKNOWN` son `NOT_FEASIBLE` para identidad o target/background.

## Modelos y resultados reales inspeccionados

Modelos implementados:

- Baselines clasicos: `logistic_regression`, `svm_rbf`, `random_forest` sobre 10 features manuales (`mean_power_dbfs`, `std_power_db`, amplitud media/std, centroide espectral, ancho espectral, CFO estimado, PAPR, kurtosis, skewness).
- `cnn1d`: I/Q crudo `[2,N]`, longitud por defecto 800, truncado o zero-padding.
- `cnn2d`: espectrograma numerico STFT, no PNG.

Resultados reales relevantes:

| Modelo/run | Dataset | Tarea | Clases | Train | Validation | Test | Lectura |
|---|---|---|---|---:|---:|---:|---|
| `AUTO-cnn1d-097402bb98` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | `keyfobdemo 02` | 1.000 | 1.000 | 1.000 | Clase unica: metricas sin valor. |
| `AUTO-cnn2d-5dfed2c161` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | `keyfobdemo 02` | 1.000 | 1.000 | 1.000 | Clase unica: metricas sin valor. |
| `AUTO-logistic_regression-10018ffd25` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | n/a | n/a | n/a | n/a | Fallo: una sola clase. |
| `AUTO-svm_rbf-c0aae3caa3` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | n/a | n/a | n/a | n/a | Fallo: una sola clase. |
| `AUTO-cnn1d-f441a4233d` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | 2 | 0.717 | 0.622 | 0.611 | Rendimiento bajo/moderado, no identidad. |
| `AUTO-cnn2d-1b15933c62` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | 2 | 0.879 | 0.838 | 0.870 | Mejor, pero detecta target/fondo, no unidad fisica entre unidades. |
| `AUTO-random_forest-f21b0cf7e1` | TARGET_VS_BACKGROUND | TARGET_VS_BACKGROUND | 2 | 1.000 | 0.897 | 0.907 | Aprobado para live pilot, pero solo para target/fondo. Train=1 sugiere posible memorizacion de artefactos de sesion/captura. |
| `AUTO-cnn2d-870016c9ab` | AUTO-DS | TARGET_VS_BACKGROUND | 2 | 0.939 | 0.621 | 0.641 | Dataset con varias unidades, pero tarea colapsada target/fondo. |
| `AUTO-random_forest-2abeaf5c25` | AUTO-DS | TARGET_VS_BACKGROUND | 2 | 1.000 | 0.653 | 0.678 | Generaliza mal fuera de TRAIN; no identidad. |

Conclusion sobre CNN: `cnn2d` mejora frente a `cnn1d` en algunos runs target/fondo, pero ninguna CNN entrenada sobre estos artefactos demuestra identificacion de dispositivo BLE. Una arquitectura potente no corrige etiquetas debiles, clases mal definidas, contaminacion ambiental ni splits que no representan el escenario real.

## Por que salen falsos positivos

### 1. La tarea entrenada no coincide con la tarea deseada

El usuario quiere detectar el dispositivo. Los runs reales inspeccionados entrenan principalmente `TARGET_VS_BACKGROUND`. En esa tarea, todos los ejemplos con `physical_unit_id` se convierten en `TARGET_DEVICE` y los negativos confirmados en `BACKGROUND_ENVIRONMENT`. Esto puede funcionar como detector de presencia bajo un setup, pero no como identificador fisico entre dispositivos BLE.

Para identificar dispositivos, la tarea debe ser `SAME_MODEL_UNIT_IDENTIFICATION` o `MULTI_DEVICE_CLASSIFICATION` con clases reales por unidad fisica, no `TARGET_DEVICE` generico.

### 2. Hubo runs historicos de una sola clase

Los runs `AUTO-cnn1d-097402bb98` y `AUTO-cnn2d-5dfed2c161` reportan 100%, pero sus `label_classes` contienen solo `keyfobdemo 02`. Eso no es aprendizaje de discriminacion: si solo existe una clase, el modelo puede acertar siempre sin distinguir nada. El codigo actual ya tiene defensas para bloquear esto, pero los artefactos historicos siguen existiendo y no deben usarse como evidencia.

### 3. La verdad-terreno depende demasiado de aislamiento fisico declarado

Solo 72 asociaciones aparecen como `STRONG`, frente a 12,092 `PHYSICAL_ISOLATION_DECLARED`. En BLE domestico o laboratorio no blindado, el ambiente puede contener decenas de emisores. El inventario nativo observo 70 identidades en 30 s, con 10 nombres locales, 10 requerian GATT y 0 parsers disponibles. Por tanto, una declaracion manual de aislamiento no basta si no se combina con control fisico estricto, target OFF real, observacion nativa, direccion esperada y auditoria de paquetes cercanos.

### 4. BLE usa direcciones que no siempre son identidad estable

BLE soporta direcciones publicas y aleatorias; las resolvable private addresses pueden cambiar durante runtime y solo son resolubles por dispositivos con IRK compartida. Por tanto, la direccion BLE decodificada no debe tratarse automaticamente como identidad fisica permanente. El proyecto acierta al tener Physical Device Registry, pero las bindings actuales son mayoritariamente declaraciones manuales/documentales.

### 5. Contaminacion ambiental BLE real

Hay evidence local de contaminacion: dos direcciones distintas en una captura atribuida por aislamiento. Esto puede producir falsos positivos porque ventanas IQ de otro transmisor entran al dataset con la etiqueta del objetivo. Un modelo entrenado con esto aprende patrones contradictorios.

### 6. Duplicados y near-duplicates no estan cerrados completamente

`DatasetAnalyzer` bloquea duplicados exactos y solapes de muestra. Eso es una fortaleza. Pero near-duplicates se marca como diagnostico no bloqueante y muchas quality reports indican `near_duplicates=NOT_EXECUTED` porque no se pasaron rutas IQ. Si hay ventanas muy parecidas dentro de una captura o bursts repetidos con payload estable, el modelo puede memorizar sesion/captura en vez de hardware.

### 7. Random Forest con train=1.0 puede estar memorizando artefactos

Varios RandomForest reales tienen train=1.0 y test/validation menores. En target/fondo esto puede seguir siendo util como piloto operativo, pero no prueba RFFI fisico. Con features como potencia, PAPR, centroide y CFO, el modelo puede explotar distancia, ganancia, orientacion, canal, ruido o condiciones de sesion.

### 8. Falta validacion OTA y congelacion DSP final

Gate 2A.2 no esta cerrado: Candidate B no esta congelado, Holdout B no existe, `iq_recovery_validated=false`, `ota_validated=false`. Si el extractor de ventanas cambia, o si no se sabe con precision que parte del paquete se esta usando, el modelo puede aprender alineacion/detector/ruido y no fingerprint.

### 9. BLE tiene paquetes cortos y condicionados por canal

BLE LE 1M usa GFSK; legacy advertising se emite en canales 37, 38 y 39. Si el dataset captura solo CH37, o mezcla canales sin balance/metadata, se introduce shift de dominio. Ademas, la parte estable para RFFI suele ser preambulo/access address porque el payload puede variar. Si el pipeline usa ventanas completas sin controlar payload/PDU, puede aprender contenido o longitud, no hardware.

## Fortalezas del proyecto

- Hay separacion clara entre adquisicion, replay, packet analysis, evidence, dataset, split, training, evaluation y bundle.
- Se conserva IQ y se referencian ventanas por `source_iq_sha256` y rangos de muestra.
- La adquisicion B200 esta instrumentada con samples esperados, tamano, overflows, discontinuidades, hash y metadatos.
- Se distingue `REAL_B200` de `SYNTHETIC_TEST_ONLY`.
- El modulo Studio no recaptura ni reetiqueta a ciegas; consume artefactos previos.
- Las etiquetas no estan embebidas directamente en `ExampleRecord`; se documentan en `ExampleAnnotation` con evidencia.
- Hay gates contra duplicados exactos y solapes de muestra.
- El split builder evita fuga por sesion/captura/rango y bloquea TRAIN de una sola clase.
- El bundle builder separa build/evaluated/aprobacion humana.
- La documentacion reconoce explicitamente limites: Gate 2A.2 no validado, capture_and_decode deshabilitado, contaminacion posible, y single-class trap.

## Puntos debiles que impiden entrenar bien

- Falta un dataset real congelado y aceptado para `SAME_MODEL_UNIT_IDENTIFICATION` con minimo dos unidades fisicas y tres sesiones independientes por unidad.
- El dataset same-model real existente esta rechazado por 728 grupos duplicados exactos.
- La mayoria de artefactos aceptados para training son target/fondo o unknown-only, no identidad.
- Hay exceso de `UNKNOWN` y `PHYSICAL_ISOLATION_DECLARED` frente a asociaciones `STRONG`.
- No hay suficiente control de ambiente BLE; el inventario muestra 70 emisores alrededor en 30 s.
- Falta negative control reforzado y clean captures finales en el estado raiz.
- No hay Holdout B ni OTA validation para Gate 2A.2.
- Near-duplicate IQ no se ejecuta en quality reports principales.
- Faltan columnas/metadatos de dominio fisico y BLE que permitan auditar drift.
- Las metricas guardadas son principalmente accuracy; faltan macro-F1, balanced accuracy, matriz de confusion, EER/FAR/FRR, calibracion por umbral y open-set rejection por dispositivo desconocido.
- Algunos bundles rechazados tienen `operational_use=ALLOWED` porque el campo parece depender solo de origen real/sintetico. El uso operacional deberia depender tambien de `approval_status` y de la tarea cientifica.

## Columnas y metadatos que faltan o deben hacerse obligatorios

No inventar datos retroactivamente. Para nuevas capturas/datasets, anadir o exigir estos campos:

### Identidad y ground truth

- `physical_unit_id` obligatorio para positivos de identidad.
- `physical_unit_serial` o identificador interno estable si existe.
- `device_family`, `manufacturer`, `model`, `hardware_revision`, `firmware_version` cuando sean observables o declarados.
- `ground_truth_method`: `address_binding`, `windows_corroborated`, `gatt_verified`, `operator_isolation`, `wired/shielded`, etc.
- `ground_truth_strength`: `STRONG`, `DOCUMENTARY`, `WEAK`, `CONFLICT`.
- `operator_id` o hash de operador si se necesita auditoria.
- `target_power_state`: `ON`, `OFF`, `REMOVED`, `UNKNOWN`.
- `isolation_method`: caja RF, distancia, habitacion limpia, apagado de otros BLE, etc.
- `ambient_ble_count_before`, `ambient_ble_count_during`, `ambient_ble_count_after`.

### BLE por paquete

- `ble_channel`: 37/38/39 para advertising; data channel 0-36 si conectado.
- `center_frequency_hz` verificado por canal.
- `phy`: LE 1M, LE 2M, LE Coded si aplica.
- `pdu_type`: ADV_IND, ADV_NONCONN_IND, SCAN_RSP, etc.
- `access_address`.
- `tx_add`, `rx_add`.
- `advertiser_address_canonical`.
- `address_type`: public, random static, RPA, NRPA, unknown.
- `payload_length`, `payload_sha256`, `manufacturer_id`, `service_uuid_count`.
- `crc_valid`, `crc_value`, `whitening_seed/channel_index` si aplica.
- `packet_start_bit`, `packet_end_bit`, `packet_start_sample`, `packet_end_sample`.

### RF/IQ por ventana

- `sample_rate_sps`, `sample_format`, `file_format`, `bandwidth_hz`.
- `rx_gain_db`, `antenna`, `clock_source`, `time_source`, `receiver_serial`.
- `iq_start_sample`, `iq_end_sample`, `window_length_samples`.
- `mean_power_dbfs`, `peak_power_dbfs`, `noise_floor_dbfs`, `snr_estimate_db`.
- `cfo_estimate_hz`, `symbol_timing_offset`, `phase_offset`, `dc_offset_i`, `dc_offset_q`, `iq_imbalance_estimate`.
- `clipping_percent`, `overflow_count`, `input_discontinuities`, `short_read_count`.
- `burst_id`, `candidate_id`, `candidate_confidence`, `rejection_reason` cuando no decode.

### Condiciones experimentales

- `session_id`, `capture_id`, `campaign_id`, `condition_id`, `day_index`.
- `distance_cm`, `orientation_deg`, `antenna_orientation`, `line_of_sight`.
- `environment_id`, `room_id`, `wifi_activity_level` si se mide, `interference_notes`.
- `temperature_c`, `battery_voltage_v` o nivel bateria si existe.
- `tx_power_setting_dbm` si el dispositivo lo permite.
- `advertising_interval_ms` si se conoce o se estima.
- `capture_duration_seconds`.

### Split/evaluacion

- `split_group_id`: unidad de no-fuga, preferiblemente sesion/campana/dia.
- `holdout_campaign_id`.
- `holdout_reason`: cross-day, cross-distance, cross-channel, unknown-device.
- `class_balance_weight` o decision de balance.
- `excluded_from_training_reason`.
- `dataset_gate_version`.

## Como entrenar correctamente con estos datos

### Paso 0: declarar la pregunta cientifica

Elegir una y no mezclar:

- `TARGET_VS_BACKGROUND`: detecta si hay senal compatible con el objetivo frente a ambiente. No identifica entre dispositivos.
- `SAME_MODEL_UNIT_IDENTIFICATION`: distingue unidades fisicas del mismo modelo/familia. Esta es la tarea que el usuario necesita para "detectar realmente el dispositivo".
- `UNKNOWN_DEVICE_REJECTION`: decide si una emision no pertenece a ningun dispositivo enrolado.

### Paso 1: cerrar captura y replay

No entrenar modelos finales hasta que:

- `iq_recovery_validated=true` para el perfil usado o, si se entrena sin decode final, que el detector de bursts/ventanas este congelado y validado.
- `ota_validated=true` para claims de paquetes BLE reales.
- Gate 2A.2 pase el criterio completo y exista Holdout B.
- Cada captura tenga cero overflows, cero discontinuidades y hash verificado.

### Paso 2: construir dataset de identidad, no de presencia

Minimo cientifico operativo recomendado para empezar, no para publicar claims generales:

- Al menos 2 unidades fisicas reales del mismo modelo; mejor 5 o mas para que el modelo no aprenda una diferencia accidental entre dos ejemplares.
- Al menos 3 sesiones independientes por unidad para poder hacer TRAIN/VALIDATION/TEST por sesion. Mejor varias sesiones en dias distintos.
- Capturas balanceadas por unidad: mismo numero aproximado de ventanas por clase.
- Capturas de CH37, CH38 y CH39 separadas o balanceadas. Si solo se usa CH37, declarar explicitamente que el modelo solo aplica a CH37.
- Positivos con asociacion fuerte o aislamiento fisico verificable; no mezclar paquetes de ambiente como positivos.
- Negativos `UNKNOWN` separados para open-set, no mezclados como si fueran otra unidad conocida salvo que sean unidades registradas.

### Paso 3: limpiar y auditar

Antes de entrenar:

- Eliminar capturas con `CONFLICT`, solapes sospechosos o contaminacion de direcciones multiples bajo aislamiento.
- Ejecutar near-duplicate con rutas IQ reales; no dejarlo en `NOT_EXECUTED` para datasets finales.
- Rechazar datasets con duplicados exactos.
- Revisar distribucion por `physical_unit_id`, `session_id`, `channel`, `capture_purpose`, `pdu_type`, `payload_length`.
- Confirmar que TRAIN/VALIDATION/TEST tienen todas las clases y sesiones distintas.

### Paso 4: representacion de senal

Para BLE, priorizar ventanas alineadas sobre partes estables:

- Preambulo + access address de advertising cuando se quiera reducir dependencia del payload.
- I/Q crudo normalizado solo con pasos justificados.
- Espectrograma numerico como alternativa robusta.
- Features basicas como baseline, no como unica evidencia.

No activar CFO correction, phase normalization, amplitude normalization o temporal alignment sin registrar tecnica y efecto esperado. CFO puede ser fingerprint real o artefacto de canal/receptor; corregirlo puede mejorar generalizacion o eliminar senal discriminativa. Debe probarse con ablation.

### Paso 5: modelos que faltan o conviene anadir

No empezar por modelos grandes. Secuencia recomendada:

1. Baseline fuerte y auditable: Logistic Regression, SVM, RandomForest/ExtraTrees con features RF y validacion por sesion/dia.
2. CNN1D sobre I/Q crudo alineado y normalizado con ablations.
3. CNN2D sobre STFT/espectrograma numerico.
4. Modelo siames/metric learning para comparar "misma unidad vs distinta unidad" y permitir enrolamiento con pocas capturas.
5. Open-set rejection con umbral calibrado en VALIDATION: distancia a centroides, energia de softmax calibrada, o score de embedding. Reportar FAR/FRR/EER.
6. Denoising autoencoder/data augmentation solo despues de tener dataset limpio, como propone literatura BLE-RFFI para robustez a SNR/canal.
7. Transformer/ViT solo como comparativa posterior; no resolvera etiquetas contaminadas.

### Paso 6: metricas de aceptacion

Para aceptar un modelo de identidad BLE, exigir al menos:

- Accuracy, balanced accuracy y macro-F1 por TEST.
- Matriz de confusion por unidad fisica.
- Recall y precision por cada dispositivo.
- FAR/false accept y FRR/false reject para unknown-device.
- Evaluacion cross-session, cross-day, cross-channel y cross-distance si esos dominios existen.
- Test con target apagado/removido.
- Test con dispositivos BLE ambientales encendidos.
- Intervalos de confianza o bootstrap si el numero de sesiones es bajo.
- Ningun split con una sola clase.
- Ningun resultado aprobado si `approval_status != APPROVED_FOR_LIVE_PILOT` y si la tarea no coincide con el uso declarado.

## Recomendaciones concretas para el programador

1. Crear un `DatasetTaskGate` que evalue el dataset contra la tarea, no solo contra duplicados. Un dataset `UNKNOWN=529` puede ser integro pero no entrenable para identidad.
2. Hacer obligatorio `near_duplicates` con rutas IQ antes de congelar datasets finales.
3. Separar en UI y API los modelos `TARGET_VS_BACKGROUND` de los modelos `DEVICE_IDENTITY`. No mostrar uno como si sirviera para el otro.
4. Cambiar `operational_use` para que sea `FORBIDDEN` si `approval_status` es `REJECTED` o si la tarea no coincide con el endpoint live.
5. Anadir macro-F1, balanced accuracy, matriz de confusion y metricas open-set a `evaluation_report.json`.
6. Anadir un reporte automatico de "label provenance": porcentaje de ejemplos `STRONG`, `PHYSICAL_ISOLATION_DECLARED`, `NONE`, `AMBIGUOUS`, `CONFLICT` por dataset y por split.
7. Bloquear identidad final si mas de un umbral definido de ejemplos positivos viene solo de `PHYSICAL_ISOLATION_DECLARED` sin corroboracion.
8. Anadir control de contaminacion: si en una captura aislada aparecen mas de N direcciones BLE distintas o direcciones no registradas con CRC valido, marcar captura como `QUARANTINED`.
9. Para same-model, impedir que `UNKNOWN` entre como clase cerrada salvo que la tarea sea explicitamente open-set.
10. Anadir `channel_balance_report`: conteo por CH37/CH38/CH39 y rendimiento por canal.
11. Anadir `session_holdout_report`: asegurar que ninguna sesion/captura/dia aparece en mas de un split.
12. Congelar un protocolo de captura multi-sesion: misma ganancia, antena, sample rate, bandwidth, canal, duracion, distancia, orientacion y procedimiento de encendido/apagado.
13. Crear campanas positivas y negativas pareadas: target ON, target OFF, otras unidades same-model ON, ambiente general.
14. Crear un modo de validacion "blind holdout": el programador/modelo no ve las etiquetas hasta terminar inferencia.
15. Registrar versiones de firmware, bateria y configuracion TX power si el SensorTag lo permite.
16. No permitir aprobacion por accuracy simple si RandomForest tiene train=1.0 y no hay prueba cross-day/cross-channel.
17. Documentar claramente en cada bundle: `scientific_task`, unidades cubiertas, canales cubiertos, condiciones cubiertas y condiciones fuera de alcance.

## Protocolo minimo propuesto para el siguiente dataset BLE profesional

Nombre sugerido: `BLE-RFFI-TI_SENSORTAG-SAME_MODEL_UNIT_IDENTIFICATION-DS__2.0.0`.

Objetivo: identificar unidad fisica entre varios TI SensorTag/keyfob del mismo modelo/familia, no detectar fondo.

Diseno minimo:

- Unidades: al menos `keyfobdemo 01`, `keyfobdemo 02`, `CC2541SensorTag`, `CC2650-UNIT-01` solo si pertenecen al mismo alcance declarado. Si no son mismo modelo, separar por tarea.
- Sesiones: minimo 3 por unidad; recomendado 5-10 por unidad.
- Dias: minimo 2; recomendado 5+.
- Canales: CH37, CH38, CH39 o declarar CH37-only.
- Capturas negativas: target OFF, otra unidad same-model ON, ambiente general.
- Asociacion: preferir `STRONG`; si se usa aislamiento, registrar auditoria ambiental y direcciones vistas.
- Split: por sesion/dia/captura completa, nunca por ventana aleatoria.
- Exclusion: cualquier captura con overflow, discontinuidad, hash no verificado, conflicto de direccion, solape no explicado o near-duplicate sospechoso.

Criterio minimo de aprobacion inicial:

- `SAME_MODEL_UNIT_IDENTIFICATION` con >=2 clases reales en TRAIN/VALIDATION/TEST.
- Macro-F1 y balanced accuracy reportadas.
- Matriz de confusion sin clase colapsada.
- False accept contra unknown/background medido, no inferido.
- Informe por canal y por sesion.
- Bundle aprobado solo si `approval_status=APPROVED_FOR_LIVE_PILOT` y `scientific_task` coincide con uso live.

## Fuentes cientificas y tecnicas consultadas

- Bluetooth Core Specification, Low Energy Controller, Radio Physical Layer: BLE opera en 2.4 GHz, usa transceptor con frequency hopping, LE 1M usa 1 Msym/s y GFSK. URL: https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-62/out/en/low-energy-controller/radio-physical-layer-specification.html
- Bluetooth LE Primer, Bluetooth SIG: legacy advertising usa canales primarios 37, 38 y 39; BLE 5 extended advertising puede mover payload a canales 0-36. URL: https://www.bluetooth.com/bluetooth-le-primer/
- Bluetooth SIG, Randomized RPA Updates: las resolvable private addresses cambian durante runtime y requieren IRK para resolucion. URL: https://www.bluetooth.com/blog/enhancing-device-privacy-and-energy-efficiency-with-bluetooth-randomized-rpa-updates/
- Yuan, Zhang, Ding, Cotton, 2025, "Robust Radio Frequency Fingerprint Identification for Bluetooth Low Energy under Low SNR and Channel Variations", IEEE WCNC: BLE-RFFI es vulnerable a variaciones de canal y bajo SNR; proponen DAE y data augmentation; usan 18 dispositivos COTS BLE y SDR USRP N210. URL: https://doi.org/10.1109/wcnc61545.2025.10978258 ; manuscript: https://researchportal.hw.ac.uk/files/146001433/Robust_RFFI_for_BLE_under_Low_SNR_and_Channel_Variations.pdf
- Herrera-Loera et al., 2026, "A transformer-based method for radio-frequency fingerprinting of IoT devices", Ad Hoc Networks: compara ViT y CNN para RFFI en GFSK/BLE-like, y estudia tamano de dataset, longitud de vector, porcion de paquete y epocas. URL: https://doi.org/10.1016/j.adhoc.2026.104155
- Wu et al., 2018, "Deep learning based RF fingerprinting for device identification and wireless security", Electronics Letters: RFFI usa rasgos hardware; el diseno experimental controla transmisores identicos y SNR. URL: https://doi.org/10.1049/el.2018.6404
- "Bluetooth Device Identification Using RF Fingerprinting and Jensen-Shannon Divergence", 2024, PMC: caso de identificacion Bluetooth por RFF y distincion entre dispositivos del mismo modelo. URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10934862/

## Dictamen final

Con los artefactos actuales, no es cientificamente riguroso afirmar que un modelo ya entrenado detecta de forma fiable un dispositivo BLE concreto. Lo que si existe es una infraestructura prometedora y bastante bien encaminada para llegar alli.

El siguiente trabajo no debe ser "probar otra CNN". Debe ser cerrar el dataset: verdad-terreno fuerte, controles negativos, mismo modelo, multi-sesion, no fugas, no duplicados, no contaminacion, canales BLE declarados y validacion holdout. Despues de eso, entrenar baselines y CNNs tiene sentido; antes de eso, cualquier accuracy alta puede ser un artefacto del dataset.
