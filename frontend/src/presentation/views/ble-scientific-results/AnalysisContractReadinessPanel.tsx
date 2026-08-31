import { useEffect, useState } from 'react';
import { AnalysisContractFieldReadiness, AnalysisContractReadiness, BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';
import { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return 'N/A';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '[]';
  return String(value);
}

/** Phase 09 (2026-08-11): Analysis Contract Readiness. NOT a generic JSON
 * editor -- every field is either DERIVED (a real, already-frozen artifact
 * or constant, read verbatim) or SCIENTIST_DECISION (a genuine judgment
 * call this UI records with a mandatory rationale, never auto-fills).
 * status is restricted to COMPLETE/INCOMPLETE/SCIENTIST_DECISION_REQUIRED.
 * Protocol Freeze Readiness is reported here for visibility only -- this
 * panel never executes a freeze. */
export default function AnalysisContractReadinessPanel({ onCompleted }: { onCompleted: () => void }) {
  const [readiness, setReadiness] = useState<AnalysisContractReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    sciApi.getAnalysisContractReadiness().then(setReadiness).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  };
  useEffect(refresh, []);

  const handleDecided = () => { refresh(); onCompleted(); };

  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-sm font-semibold text-slate-200">Analysis Contract Readiness (fase 09)</div>
      <div className="mt-1 text-xs text-slate-500">
        Cada campo del contrato confirmatorio es DERIVED (un artefacto o constante ya congelada, leida tal cual --
        nunca inventada) o SCIENTIST_DECISION (un juicio cientifico real que solo un cientifico puede registrar, con
        rationale obligatoria). No es un editor JSON generico. Ninguna decision puede citar el holdout FUTURE
        protegido como evidencia.
      </div>
      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
      {!readiness && !error && <div className="mt-2 text-xs text-slate-500">Cargando readiness...</div>}

      {readiness && (
        <>
          <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-300">PROTOCOL FREEZE READINESS</span>
              <StatusBadge status={readiness.protocol_freeze_readiness.status} />
              <span className="text-[11px] text-slate-600">(solo lectura -- el freeze no se ejecuta desde este panel)</span>
            </div>
            {readiness.protocol_freeze_readiness.missing.length > 0 && (
              <div className="mt-1 text-[11px] text-red-400">
                Missing: {readiness.protocol_freeze_readiness.missing.join(', ')}
              </div>
            )}
          </div>

          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold text-slate-300">Readiness gates</div>
            <div className="grid gap-1 sm:grid-cols-2">
              {readiness.readiness_gates.map((gate) => (
                <div key={gate.gate_id} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950 px-2 py-1 text-[11px]">
                  <span className="text-slate-400">{gate.label}</span>
                  <StatusBadge status={gate.status} />
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 overflow-x-auto">
            <div className="mb-1 text-xs font-semibold text-slate-300">Contract fields</div>
            <table className="w-full min-w-[720px] border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 text-left text-slate-500">
                  <th className="py-1 pr-2 font-medium">Field</th>
                  <th className="py-1 pr-2 font-medium">Kind</th>
                  <th className="py-1 pr-2 font-medium">Value</th>
                  <th className="py-1 pr-2 font-medium">Source</th>
                  <th className="py-1 pr-2 font-medium">Evidence maturity</th>
                  <th className="py-1 pr-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {readiness.fields.map((field) => (
                  <FieldRow key={field.field_id} field={field} onDecided={handleDecided} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function FieldRow({ field, onDecided }: { field: AnalysisContractFieldReadiness; onDecided: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <tr className="border-b border-slate-900 align-top">
        <td className="py-1.5 pr-2 text-slate-200">{field.label}</td>
        <td className="py-1.5 pr-2 text-slate-500">{field.kind}</td>
        <td className="py-1.5 pr-2 font-mono text-slate-300">{formatValue(field.value)}</td>
        <td className="py-1.5 pr-2 text-slate-500">{field.source ?? 'N/A'}</td>
        <td className="py-1.5 pr-2 text-slate-500">{field.evidence_maturity ?? 'N/A'}</td>
        <td className="py-1.5 pr-2">
          <div className="flex items-center gap-2">
            <StatusBadge status={field.status} />
            {field.kind === 'SCIENTIST_DECISION' && (
              <button className="text-cyan-400 hover:underline" onClick={() => setExpanded((v) => !v)}>
                {expanded ? 'cerrar' : field.status === 'COMPLETE' ? 'revisar' : 'decidir'}
              </button>
            )}
          </div>
        </td>
      </tr>
      {field.rationale && !expanded && (
        <tr className="border-b border-slate-900">
          <td colSpan={6} className="py-1 pr-2 text-[11px] text-slate-600">rationale: {field.rationale}</td>
        </tr>
      )}
      {expanded && (
        <tr className="border-b border-slate-900">
          <td colSpan={6} className="py-2 pr-2">
            <ScientistDecisionForm fieldId={field.field_id} onDecided={() => { setExpanded(false); onDecided(); }} />
          </td>
        </tr>
      )}
    </>
  );
}

function ScientistDecisionForm({ fieldId, onDecided }: { fieldId: string; onDecided: () => void }) {
  const [selectedValue, setSelectedValue] = useState('');
  const [rationale, setRationale] = useState('');
  const [evidenceUsed, setEvidenceUsed] = useState('');
  const [decidedBy, setDecidedBy] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!rationale.trim()) { setError('Se requiere una rationale real para registrar la decision.'); return; }
    setError(null);
    setBusy(true);
    try {
      let parsedValue: unknown = selectedValue;
      try { parsedValue = JSON.parse(selectedValue); } catch { /* plain string value is fine */ }
      await sciApi.recordScientistDecision({
        field_id: fieldId, selected_value: parsedValue, rationale,
        evidence_used: evidenceUsed || undefined, decided_by: decidedBy || undefined,
      });
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      {error && <div className="mb-2 text-[11px] text-red-400">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">selected_value (JSON o texto)</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={selectedValue} onChange={(e) => setSelectedValue(e.target.value)} disabled={busy} />
        </div>
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">decided_by (opcional)</label>
          <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} disabled={busy} />
        </div>
      </div>
      <div className="mt-2">
        <label className="mb-1 block text-[11px] text-slate-500">evidence_used (nunca puede citar FUTURE)</label>
        <input className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={evidenceUsed} onChange={(e) => setEvidenceUsed(e.target.value)} disabled={busy} />
      </div>
      <div className="mt-2">
        <label className="mb-1 block text-[11px] text-slate-500">rationale (obligatoria)</label>
        <textarea className="h-16 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={rationale} onChange={(e) => setRationale(e.target.value)} disabled={busy} />
      </div>
      <button className="mt-2 rounded bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-700" disabled={busy || !rationale.trim()} onClick={submit}>
        Registrar decision cientifica
      </button>
    </div>
  );
}
