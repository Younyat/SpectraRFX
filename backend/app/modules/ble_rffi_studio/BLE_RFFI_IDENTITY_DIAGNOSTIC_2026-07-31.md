# Diagnóstico: ¿el pipeline BLE-RFFI aprende identidad física real, hoy?

Fecha: 2026-07-31
Alcance: experimento mínimo, real, sin código nuevo — reutiliza 100% la infraestructura ya existente
(Dataset Builder, Split Builder, Training Service, `prepare_and_train`).

## Pregunta

El operador reportó que ningún modelo BLE-RFFI llega a identificar correctamente la identidad de un
dispositivo físico, aunque algunos alcancen validación alta en otras tareas. Antes de rediseñar nada
(campaña multicanal, nuevas representaciones, etc.) había que responder algo más simple y previo:
**¿se ha intentado siquiera entrenar identidad con datos reales, y qué pasa quando se hace?**

## Hallazgo 0: nunca se había intentado

`GET /training-runs` mostró 27 ejecuciones completadas de `SAME_MODEL_UNIT_IDENTIFICATION` — las 27 con
`data_origin=SYNTHETIC_DEMO`. Cero con `REAL_B200`. Todo el entrenamiento real de esta sesión había sido
`TARGET_VS_BACKGROUND` (detectar presencia, no identidad). La afirmación "ningún modelo llega a identidad"
describía, hasta hoy, algo nunca puesto a prueba con datos reales.

## El experimento

Datos: 35 capturas reales B200, `device_source=ADDRESS_MATCH` (identidad confirmada por decodificación de
dirección, no solo aislamiento declarado), de 3 unidades físicas de la misma familia de hardware
(`TI sensortag`): `keyfobdemo 01` (21 capturas), `keyfobdemo 02` (9), `CC2541SensorTag` (5). Capturadas en
3 días distintos (2026-07-28, 29, 30).

Dataset: `BLE-RFFI-IDENTITY-EXPERIMENT-DS` v1.0.0, 13061 ejemplos elegibles, control de calidad limpio tras
usar `resolve_overlaps()` (2 pares solapados encontrados y resueltos automáticamente). Split
`SAME_MODEL_UNIT_IDENTIFICATION` construido con `SplitBuilder`, `split_status=READY`,
`leakage_check=PASSED` (session-disjoint: ninguna sesión aparece en más de una partición).

Entrenamiento: `prepare_and_train`, perfil `normal` (incluye CNN), 5 candidatos:
`logistic_regression`, `svm_rbf`, `random_forest`, `cnn1d`, `cnn2d`.

## Resultado real

```
stopped_at: model_selection
stopped_reason: NO_MODEL_ACCEPTED — ninguno de los 5 candidatos alcanzó
  macro_f1 >= 0.5 ni balanced_accuracy >= 0.5 en VALIDATION.
```

| Modelo | composite_score |
|---|---:|
| random_forest | 0.247 |
| cnn1d | 0.234 |
| cnn2d | 0.233 |
| logistic_regression | 0.209 |
| svm_rbf | 0.038 |

Ninguno se recomendó. Ninguno se evaluó sobre TEST (correcto: TEST se reserva para el modelo
seleccionado, y aquí no hubo selección — el mismo criterio que ya verificamos que el pipeline respeta).

### La prueba concreta de qué está pasando (random_forest, el mejor de los 5)

```
TRAIN:      accuracy 1.000, macro-F1 1.000 — confusión perfecta, cero errores.
VALIDATION: accuracy 0.665, macro-F1 0.293
  recall keyfobdemo 01:      1.00  (351/351)
  recall keyfobdemo 02:      0.00  (0/77)   <- nunca acierta, ni una vez
  recall CC2541SensorTag:    0.00  (0/100)  <- nunca acierta, ni una vez
```

`logistic_regression` reproduce el mismo patrón con otro tipo de modelo por completo (lineal, no árboles):
recall `keyfobdemo 02` = 0.0, recall `CC2541SensorTag` = 0.02 (2 de 100, ruido).

**Esto no es un problema de qué algoritmo se elige.** Cuatro arquitecturas muy distintas (lineal, kernel,
árboles, dos CNN) colapsan de la misma forma exacta: memorizan perfectamente las sesiones de TRAIN
(1.0 de accuracy) y fallan por completo en sesiones nuevas de las clases minoritarias, aunque sean el
mismo dispositivo físico. Eso es la firma clásica de un modelo aprendiendo **la sesión de captura, no el
hardware** — exactamente lo que tanto el documento de rediseño del operador como la auditoría externa de
ORACLE/KRI (`README_INSPECCION_DATASETS_ORACLE.md`) advierten como el riesgo principal en RFFI.

## Por qué, con los datos que ya existen

Tres factores reales, verificados con los propios reportes del pipeline sobre este dataset exacto
(no especulación):

1. **`strong_fraction: 0.0`** (`label-provenance`). Ninguno de los 13061 ejemplos tiene verdad de
   referencia `STRONG` (dirección + corroboración nativa Windows, independiente). El resto es `NONE`
   (65.3%, sin coincidencia de dirección en ese paquete concreto) o `PHYSICAL_ISOLATION_DECLARED` (33.2%,
   confiado al operador). La identidad de clase entra por `physical_unit_id` vía dirección decodificada,
   que es razonable, pero no hay ninguna capa de verificación independiente por encima.
2. **Un solo canal BLE, tres días** (`composition-report`): `channel_counts: {"37": 13061}`. Cero
   variación de canal. Si el receptor introduce cualquier sesgo dependiente de la sintonización (no
   descartado), el modelo no tiene forma de distinguirlo de la identidad del transmisor.
3. **Desbalance severo y pocas sesiones por clase**: TRAIN tiene 19 sesiones de `keyfobdemo 01` frente a
   7 de `keyfobdemo 02` y solo 3 de `CC2541SensorTag`; VALIDATION y TEST tienen exactamente **una sola
   sesión por clase**. Con una sola sesión de validación por clase, "aprender esa sesión" y "aprender el
   dispositivo" son estadísticamente casi indistinguibles — no hay forma de promediar el ruido de una
   sesión concreta.

Ninguno de estos tres factores es un bug de código. Los tres son exactamente el tipo de brecha que Fase 5
(cobertura de canal, más sesiones balanceadas, intercalado) y Fase 6 (política de etiquetas) del documento
de rediseño ya identifican — confirmado ahora con un experimento real, no solo con literatura externa.

## Veredicto

**No, con los datos reales que existen hoy, el pipeline no aprende identidad física fiable entre
`keyfobdemo 01`, `keyfobdemo 02` y `CC2541SensorTag`.** El resultado no es "casi bueno" ni "necesita
ajustar hiperparámetros" — es memorización de sesión con fallo total (recall 0.0) en las clases con menos
sesiones, reproducido de forma idéntica en 4 arquitecturas distintas. Cambiar de modelo, de librería o de
hiperparámetros no va a arreglar esto: el problema está en cuántas sesiones independientes y cuánta
diversidad de condición (canal, día, distancia) hay detrás de cada clase, no en el clasificador.

## Qué haría falta, en orden de impacto real (no las 14 fases completas todavía)

1. **Más sesiones independientes por clase**, sobre todo para `keyfobdemo 02` (9→¿20+?) y
   `CC2541SensorTag` (5→¿20+?), para que VALIDATION/TEST dejen de depender de una sola sesión por clase.
2. **Intercalar el orden de captura** entre unidades (nunca capturar todas las sesiones de una unidad
   seguidas) — ya lo pide el documento de rediseño (Fase 5), y aquí se ve por qué: las sesiones de
   `keyfobdemo 02` y `CC2541SensorTag` se capturaron en bloques consecutivos el mismo día, coincidiendo
   justo con el tipo de confusión (condición temporal/ambiental) que el modelo parece estar aprendiendo.
3. **Al menos un segundo canal BLE** (38 o 39) para las mismas unidades, para poder comprobar si el
   "fingerprint" sobrevive a cambiar de sintonización — sin esto, no se puede ni empezar a descartar que
   el modelo esté aprendiendo la respuesta del receptor en el canal 37.
4. Recién entonces, si el problema persiste, tiene sentido invertir en representaciones nuevas (R1-R5,
   TPD) — con los datos actuales, cambiar de representación no solucionaría un problema que es de
   cantidad/diversidad de sesiones, no de qué características se extraen.

Este documento no propone ejecutar 1-4 todavía — es el insumo para decidir, con el operador, cuál de ellos
merece la próxima campaña de captura real.
