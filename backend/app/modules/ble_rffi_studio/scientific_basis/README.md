# scientific_basis/

Respaldo teorico y de literatura para las decisiones de diseno del modulo
`ble_rffi_studio`. Ningun contenido aqui se fabrica: una entrada solo se
anade cuando hay una fuente real (paper, preprint, protocolo documentado)
detras de ella. Si no existe fuente verificada todavia, la decision se deja
en `pending_research`, nunca como una entrada inventada.

## Archivos

- `technique_registry.json` -- una entrada por tecnica/paper considerado,
  con `applicability_status` en `DIRECTLY_APPLICABLE | PARTIALLY_APPLICABLE |
  REFERENCE_ONLY | NOT_APPLICABLE`. Usar una CNN no es motivo suficiente para
  incluir un paper: la entrada debe declarar que parte es transferible a
  BLE-RFFI y cual no.
- `preprocessing_evidence.json` -- por cada paso de preprocesamiento que
  altera la senal (CFO, fase, amplitud, alineacion temporal, eliminacion de
  transitorios), declara que variacion elimina, que huella fisica podria
  borrar, que `technique_id` lo justifica, y si esta habilitado por defecto
  (nunca lo esta salvo justificacion explicita).
- `model_evidence.json` -- evidencia por familia de modelo (LR, SVM, RF,
  CNN1D, CNN2D). Vacio hasta Fase 3/4: no se declara evidencia sobre un
  modelo que aun no existe.

## Regla de oro

Toda tecnica, paso de preprocesamiento o eleccion de modelo que altere la
senal o afecte una decision de aceptacion de dataset/modelo debe ser
trazable a una entrada de este directorio con `technique_id` explicito, o
debe quedar marcada como pendiente de investigacion real.
