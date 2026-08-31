import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, ExperimentHealthSummary } from '../../../app/services/bleScientificResultsApi';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

function ratioColor(completed: number, scheduled: number): string {
  if (scheduled === 0) return 'bg-slate-900 text-slate-600';
  const ratio = completed / scheduled;
  if (ratio >= 1) return 'bg-emerald-900/50 text-emerald-300';
  if (ratio > 0) return 'bg-amber-900/50 text-amber-300';
  return 'bg-red-950/50 text-red-400';
}

/** Level A -- Experiment Health (2026-08-11). Every number here is a real
 * cross-reference read from get_experiment_health_summary() -- real
 * PaperCampaignSchedule entries, real rejections.jsonl counts, real
 * campaign_deviations rows. No decorative gauges: the completion cells
 * below show the real completed/scheduled fraction as text plus a plain
 * color band, never a synthetic KPI ring. */
export default function ExperimentHealthTab() {
  const [summary, setSummary] = useState<ExperimentHealthSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    sciApi.getExperimentHealth().then(setSummary).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const allUnits = summary ? Array.from(new Set(summary.campaigns.flatMap((c) => c.physical_units))).sort() : [];

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">A. Experiment Health</div>
        <div className="mt-1 text-xs text-slate-500">
          Estado de la maquinaria experimental -- cronologia del estudio, completitud de campana, estado de
          asociacion/protocolo/holdout, y distribucion real de fallos/rechazos. Cada numero proviene de un artefacto
          real (PaperCampaignSchedule, rejections.jsonl, campaign_deviations) -- nunca una estimacion.
        </div>
      </div>
      {error && <div className="text-xs text-red-400">{error}</div>}
      {!summary && !error && <div className="text-xs text-slate-500">Cargando...</div>}

      {summary && (
        <>
          <div className="flex flex-wrap gap-3 text-xs">
            <span className="flex items-center gap-1"><span className="text-slate-500">association</span><StatusBadge status={summary.association_policy_status} /></span>
            <span className="flex items-center gap-1"><span className="text-slate-500">protocol freeze</span><StatusBadge status={summary.protocol_freeze_status} /></span>
            <span className="flex items-center gap-1"><span className="text-slate-500">protected FUTURE</span><StatusBadge status={summary.protected_future_test_status} /></span>
          </div>

          {summary.campaigns.length === 0 && <NoDataNotice reason="Ningun PaperCampaignSchedule congelado todavia -- ninguna campana real ha comenzado." />}

          {summary.campaigns.length > 0 && (
            <>
              <div>
                <div className="mb-1 text-xs font-semibold text-slate-400">Cronologia del estudio (por frozen_at real)</div>
                <div className="flex flex-wrap gap-2">
                  {[...summary.campaigns].sort((a, b) => (a.frozen_at ?? '').localeCompare(b.frozen_at ?? '')).map((c) => (
                    <div key={c.schedule_id} className="rounded border border-slate-800 bg-slate-950 px-2 py-1 text-[11px]">
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-200">{c.schedule_id}</span>
                        <EvidenceMaturityBadge maturity={c.evidence_maturity} />
                      </div>
                      <div className="text-slate-600">{c.frozen_at ?? 'N/A'}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="overflow-x-auto">
                <div className="mb-1 text-xs font-semibold text-slate-400">Campanas / runs</div>
                <table className="w-full min-w-[900px] border-collapse text-[11px]">
                  <thead>
                    <tr className="border-b border-slate-800 text-left text-slate-500">
                      <th className="py-1 pr-2 font-medium">Schedule (campaign_id)</th>
                      <th className="py-1 pr-2 font-medium">Evidence maturity</th>
                      <th className="py-1 pr-2 font-medium">protocol_id</th>
                      <th className="py-1 pr-2 font-medium">Scheduled</th>
                      <th className="py-1 pr-2 font-medium">Completed</th>
                      <th className="py-1 pr-2 font-medium">Incomplete</th>
                      <th className="py-1 pr-2 font-medium">Rejected attempts</th>
                      <th className="py-1 pr-2 font-medium">Physical units</th>
                      <th className="py-1 pr-2 font-medium">paper_run_id(s)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.campaigns.map((c) => (
                      <tr key={c.schedule_id} className="border-b border-slate-900 text-slate-300">
                        <td className="py-1.5 pr-2 text-slate-200">{c.schedule_id} <span className="text-slate-600">v{c.schedule_version}</span></td>
                        <td className="py-1.5 pr-2"><EvidenceMaturityBadge maturity={c.evidence_maturity} /></td>
                        <td className="py-1.5 pr-2 font-mono text-slate-500">{c.protocol_id}</td>
                        <td className="py-1.5 pr-2 font-mono">{c.scheduled_blocks}</td>
                        <td className="py-1.5 pr-2 font-mono">{c.completed_blocks}</td>
                        <td className="py-1.5 pr-2 font-mono">{c.incomplete_blocks}</td>
                        <td className="py-1.5 pr-2 font-mono">{c.rejected_attempt_count}</td>
                        <td className="py-1.5 pr-2 text-slate-500">{c.physical_units.join(', ') || 'N/A'}</td>
                        <td className="py-1.5 pr-2 text-slate-500">{c.paper_run_ids.join(', ') || 'N/A'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="overflow-x-auto">
                <div className="mb-1 text-xs font-semibold text-slate-400">Block completion heatmap (schedule x unidad fisica, real completed/scheduled)</div>
                <table className="border-collapse text-[11px]">
                  <thead>
                    <tr>
                      <th className="border border-slate-800 px-2 py-1 text-left text-slate-500">schedule</th>
                      {allUnits.map((unit) => <th key={unit} className="border border-slate-800 px-2 py-1 text-slate-500">{unit}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {summary.campaigns.map((c) => (
                      <tr key={c.schedule_id}>
                        <td className="border border-slate-800 px-2 py-1 text-slate-300">{c.schedule_id}</td>
                        {allUnits.map((unit) => {
                          const cell = c.blocks_by_physical_unit[unit];
                          return (
                            <td key={unit} className={`border border-slate-800 px-2 py-1 text-center font-mono ${cell ? ratioColor(cell.completed_blocks, cell.scheduled_blocks) : 'bg-slate-950 text-slate-700'}`}>
                              {cell ? `${cell.completed_blocks}/${cell.scheduled_blocks}` : '-'}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div>
            <div className="mb-1 text-xs font-semibold text-slate-400">Distribucion de fallos/rechazos (deviation_type real -- campaign_deviations.py)</div>
            {Object.keys(summary.deviation_type_distribution).length === 0 ? (
              <NoDataNotice reason="No hay campaign_deviations reales todavia (records aun no construidos para ningun run, o ninguna desviacion real registrada)." />
            ) : (
              <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                {Object.entries(summary.deviation_type_distribution).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                  <div key={type} className="rounded border border-slate-800 bg-slate-950 p-2">
                    <div className="text-slate-500">{type}</div>
                    <div className="font-mono text-slate-200">{count}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
