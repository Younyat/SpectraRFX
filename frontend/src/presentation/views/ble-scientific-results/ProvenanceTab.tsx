import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, DecisionProvenance, InferenceRunSummary } from '../../../app/services/bleScientificResultsApi';
import MechanismDataNotice from './MechanismDataNotice';
import NoDataNotice from './NoDataNotice';
import { StatusBadge } from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

const CHAIN_STEPS: { label: string; render: (p: DecisionProvenance) => string | null | undefined }[] = [
  { label: 'inference_run', render: (p) => p.inference_run_id },
  { label: 'bundle', render: (p) => (p.bundle_id ? `${p.bundle_id} (${p.bundle_sha256 ?? '?'})` : null) },
  { label: 'decision', render: (p) => (p.decision ? `${p.decision.predicted_class ?? '?'} / ${p.decision.final_decision ?? '?'}` : null) },
  { label: 'example -> capture', render: (p) => (p.capture_id ? `${p.example_id} -> ${p.capture_id} [${p.sample_start}:${p.sample_end}]` : null) },
  { label: 'I/Q sha256', render: (p) => p.capture_iq_sha256 },
  { label: 'PDU recuperado', render: (p) => (p.recovered_pdu_evidence ? `${p.recovered_pdu_evidence.pdu_type ?? '?'} (${p.recovered_pdu_evidence.association_strength ?? '?'})` : null) },
  { label: 'dataset', render: (p) => (p.dataset_id ? `${p.dataset_id}__${p.dataset_version} (${p.dataset_manifest_sha256 ?? '?'})` : null) },
  { label: 'split', render: (p) => (p.scientific_task ? `${p.scientific_task} (${p.split_manifest_sha256 ?? '?'})` : null) },
];

/** Provenance reconstruction (2026-08-11): real read-only chain walk over
 * `(inference_run_id, example_id)` -- the only real addressable decision
 * unit today (there is no single persisted decision_id anywhere). Never
 * reconstructs via heuristics; every link either resolves to a real,
 * already-persisted value or is reported honestly in missing_link. */
export default function ProvenanceTab() {
  const [runs, setRuns] = useState<InferenceRunSummary[]>([]);
  const [inferenceRunId, setInferenceRunId] = useState('');
  const [exampleId, setExampleId] = useState('');
  const [provenance, setProvenance] = useState<DecisionProvenance | null>(null);

  useEffect(() => {
    sciApi.listInferenceRuns().then(setRuns).catch(() => setRuns([]));
  }, []);

  const selectedRun = runs.find((r) => r.inference_run_id === inferenceRunId);

  useEffect(() => {
    if (!inferenceRunId || !exampleId) { setProvenance(null); return; }
    sciApi.getDecisionProvenance(inferenceRunId, exampleId).then(setProvenance).catch(() => setProvenance(null));
  }, [inferenceRunId, exampleId]);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Provenance</div>
        <div className="mt-1 text-xs text-slate-500">
          decision -&gt; window -&gt; bursts -&gt; examples -&gt; PDU recuperado -&gt; sample_start/end -&gt; capture_id -&gt; I/Q
          SHA-256, mas dataset/split manifest, perfil de preprocesamiento, bundle de modelo, protocol_version,
          contract_sha256 y git SHA. La unidad direccionable real es (inference_run_id, example_id) -- no existe un
          decision_id unico persistido en ningun lugar del sistema.
        </div>
      </div>
      <MechanismDataNotice
        data={runs.length > 0 ? 'AVAILABLE' : 'NO_DATA'}
        dataReason="No existe todavia ninguna inference_runs/<id>.json real -- el endpoint de reconstruccion (reconstruct_decision_provenance) esta implementado y probado (cadena completa, enlace faltante, hash mismatch)."
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-slate-500">inference_run_id</label>
          <select className={READ_ONLY_PICKER_CLASS} value={inferenceRunId} onChange={(e) => { setInferenceRunId(e.target.value); setExampleId(''); }}>
            <option value="">(seleccionar inference run)</option>
            {runs.map((run) => (<option key={run.inference_run_id} value={run.inference_run_id}>{run.inference_run_id}</option>))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-500">example_id</label>
          <select className={READ_ONLY_PICKER_CLASS} value={exampleId} onChange={(e) => setExampleId(e.target.value)} disabled={!selectedRun}>
            <option value="">(seleccionar example)</option>
            {selectedRun?.example_ids.map((id) => (<option key={id} value={id}>{id}</option>))}
          </select>
        </div>
      </div>

      {runs.length === 0 && <NoDataNotice reason="Ningun inference_runs/<id>.json real todavia -- reconstruccion imposible sin una decision real." />}
      {runs.length > 0 && (!inferenceRunId || !exampleId) && <NoDataNotice reason="Selecciona un inference run y un example_id para reconstruir la cadena." />}

      {provenance && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">provenance_status</span>
            <StatusBadge status={provenance.provenance_status} />
          </div>
          <div className="space-y-1">
            {CHAIN_STEPS.map((step) => {
              const value = step.render(provenance);
              return (
                <div key={step.label} className="flex items-center gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-1.5 text-xs">
                  <span className="w-40 shrink-0 text-slate-500">{step.label}</span>
                  {value ? (
                    <span className="font-mono text-slate-200">{value}</span>
                  ) : (
                    <span className="font-mono text-amber-400">missing_link</span>
                  )}
                </div>
              );
            })}
          </div>
          {provenance.missing_link.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold text-amber-400">missing_link</div>
              <ul className="list-inside list-disc text-xs text-slate-400">
                {provenance.missing_link.map((link) => (<li key={link}>{link}</li>))}
              </ul>
            </div>
          )}
          {provenance.hash_mismatch.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold text-red-400">hash_mismatch</div>
              <ul className="list-inside list-disc text-xs text-slate-400">
                {provenance.hash_mismatch.map((mismatch) => (<li key={mismatch}>{mismatch}</li>))}
              </ul>
            </div>
          )}
          <details className="rounded border border-slate-800 bg-slate-950">
            <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-400">JSON crudo (fuente exacta persistida)</summary>
            <pre className="max-h-[70vh] overflow-auto p-3 text-[11px] text-slate-300">{JSON.stringify(provenance, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
