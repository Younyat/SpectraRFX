import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, StudyStatusResponse } from '../../../app/services/bleScientificResultsApi';
import { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

export default function StudyOverviewTab() {
  const [status, setStatus] = useState<StudyStatusResponse | null>(null);

  useEffect(() => {
    sciApi.studyStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  if (!status) {
    return <div className="p-4 text-xs text-slate-500">Cargando estado del estudio...</div>;
  }

  const timeline: { label: string; done: boolean }[] = [
    { label: 'Code freeze', done: true },
    { label: 'Qualification', done: false },
    { label: 'Calibration', done: status.association_policy_status === 'FROZEN' },
    { label: 'Pilot', done: false },
    { label: 'Development', done: false },
    { label: 'Validation', done: false },
    { label: 'Protocol freeze', done: status.protocol_freeze_status === 'COMPLETE' },
    { label: 'Definitive campaign', done: false },
    { label: 'FUTURE', done: status.protected_future_test_status === 'OPENED' },
    { label: 'Results', done: false },
    { label: 'Paper', done: false },
  ];

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Study overview</div>
        <div className="mt-1 text-xs text-slate-500">
          Vista de solo lectura, agregada a partir de artefactos canonicos reales. No calcula ciencia -- solo lee lo
          que ya existe en disco.
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
        <Field label="Git SHA" value={status.git_sha.slice(0, 12)} />
        <Field label="Protocol ID" value={status.protocol_id ?? '(none)'} />
        <Field label="Protocol version" value={status.protocol_version != null ? String(status.protocol_version) : '(none)'} />
        <Field label="Real capture count" value={String(status.real_capture_count)} />
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-400">¿El experimento esta sano?</div>
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
          <StatusRow label="AnalysisContract" status={status.contract_status} />
          <StatusRow label="Association" status={status.association_policy_status} />
          <StatusRow label="Protocol freeze" status={status.protocol_freeze_status} />
          <StatusRow label="Protected FUTURE" status={status.protected_future_test_status} />
        </div>
      </div>

      {status.missing_confirmatory_readiness_fields.length > 0 && (
        <div className="rounded border border-amber-800 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
          Campos de disposicion confirmatoria pendientes en el contrato actual: {status.missing_confirmatory_readiness_fields.join(', ')}
        </div>
      )}

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-400">Current phase</div>
        <div className="rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">{status.current_phase}</div>
      </div>

      <div>
        <div className="mb-2 text-xs font-semibold text-slate-400">Timeline</div>
        <div className="flex flex-wrap items-center gap-1 text-[11px]">
          {timeline.map((step, index) => (
            <div key={step.label} className="flex items-center gap-1">
              <span className={`rounded px-2 py-1 ${step.done ? 'bg-emerald-900/40 text-emerald-300' : 'bg-slate-800 text-slate-500'}`}>{step.label}</span>
              {index < timeline.length - 1 && <span className="text-slate-700">-&gt;</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="text-[11px] text-slate-600">generated_at: {status.generated_at}</div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-900/60 px-2 py-1.5">
      <div className="text-slate-500">{label}</div>
      <div className="truncate font-mono text-slate-200">{value}</div>
    </div>
  );
}

function StatusRow({ label, status }: { label: string; status: string }) {
  return (
    <div className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
      <span className="text-slate-400">{label}</span>
      <StatusBadge status={status} />
    </div>
  );
}
