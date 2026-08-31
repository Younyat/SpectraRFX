import { useEffect, useMemo, useState } from 'react';
import { BleScientificResultsApiService, EvidenceQualitySummary, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import EcdfChart from './charts/EcdfChart';
import HistogramChart from './charts/HistogramChart';
import NoDataNotice from './NoDataNotice';
import { READ_ONLY_PICKER_CLASS, useReadOnlyRuns } from './useReadOnlyRuns';

const sciApi = new BleScientificResultsApiService();

function isNoData(summary: EvidenceQualitySummary | NoDataResponse | null): summary is NoDataResponse {
  return !!summary && (summary as NoDataResponse).status === 'NO_DATA';
}

function filterByUnit(perCapture: Record<string, number>, unitByCapture: Record<string, string>, unit: string): Record<string, number> {
  return Object.fromEntries(Object.entries(perCapture).filter(([captureId]) => unitByCapture[captureId] === unit));
}

function CountTable({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-slate-400">{title}</div>
      {entries.length === 0 ? (
        <NoDataNotice reason="Sin filas reales todavia." />
      ) : (
        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
          {entries.sort((a, b) => b[1] - a[1]).map(([key, count]) => (
            <div key={key} className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-slate-500">{key}</div>
              <div className="font-mono text-slate-200">{count}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Level B -- Data/Evidence Quality (2026-08-11). Every table/histogram/
 * ECDF here groups already-real per-capture/per-burst/per-window canonical
 * rows (get_evidence_quality_summary) -- captures/unit/day/role,
 * candidate-bursts/CRC-valid/admitted per capture, exclusion reasons,
 * eligible bursts per window, usable windows, insufficient-evidence
 * abstentions, discontinuities. NO_DATA (never a zeroed table) when the
 * canonical record tables have not been built for the selected run. */
export default function EvidenceQualityTab() {
  const { runs, paperRunId, setPaperRunId } = useReadOnlyRuns();
  const [summary, setSummary] = useState<EvidenceQualitySummary | NoDataResponse | null>(null);
  const [unitFilter, setUnitFilter] = useState('');

  useEffect(() => {
    if (!paperRunId) { setSummary(null); return; }
    setUnitFilter('');
    sciApi.getEvidenceQualitySummary(paperRunId).then(setSummary).catch(() => setSummary({ status: 'NO_DATA' }));
  }, [paperRunId]);

  const filtered = useMemo(() => {
    if (!summary || isNoData(summary) || !unitFilter) return null;
    return {
      candidate: filterByUnit(summary.candidate_bursts_per_capture, summary.physical_unit_by_capture_id, unitFilter),
      crcValid: filterByUnit(summary.crc_valid_per_capture, summary.physical_unit_by_capture_id, unitFilter),
      admitted: filterByUnit(summary.admitted_per_capture, summary.physical_unit_by_capture_id, unitFilter),
    };
  }, [summary, unitFilter]);

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">B. Data / Evidence Quality</div>
        <div className="mt-1 text-xs text-slate-500">
          Agrupaciones reales sobre las tablas canonicas ya construidas (capture_records/burst_records/
          decision_window_records/campaign_deviations) -- nunca una cifra recomputada. NO_DATA cuando los records de
          este run todavia no se han construido.
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs text-slate-500">paper_run_id</label>
        <select className={READ_ONLY_PICKER_CLASS} value={paperRunId} onChange={(e) => setPaperRunId(e.target.value)}>
          <option value="">(seleccionar run)</option>
          {runs.map((run) => (<option key={run.paper_run_id} value={run.paper_run_id}>{run.paper_run_id}</option>))}
        </select>
      </div>

      {!paperRunId && <NoDataNotice reason="Ningun paper run seleccionado." />}
      {paperRunId && isNoData(summary) && <NoDataNotice reason="Los canonical records (build_records) no se han construido todavia para este run." />}

      {paperRunId && summary && !isNoData(summary) && (
        <>
          <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-5">
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">captures</div><div className="font-mono text-slate-200">{summary.capture_count}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">bursts</div><div className="font-mono text-slate-200">{summary.burst_count}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">windows</div><div className="font-mono text-slate-200">{summary.window_count}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">usable windows</div><div className="font-mono text-slate-200">{summary.usable_windows}</div></div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2"><div className="text-slate-500">insufficient-evidence abstentions</div><div className="font-mono text-slate-200">{summary.insufficient_evidence_abstention_windows}</div></div>
          </div>

          <CountTable title="Captures / unidad fisica" counts={summary.captures_per_physical_unit} />
          <CountTable title="Captures / dia" counts={summary.captures_per_day} />
          <CountTable title="Captures / rol experimental" counts={summary.captures_per_experimental_role} />
          <CountTable title="Distribucion de razones de exclusion (blocking_reason_codes reales)" counts={summary.exclusion_reason_counts} />

          <div className="flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2">
            <label className="text-xs text-slate-500">Filtro cientifico -- unidad fisica:</label>
            <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={unitFilter} onChange={(e) => setUnitFilter(e.target.value)}>
              <option value="">(sin filtro -- vista canonica)</option>
              {Object.keys(summary.captures_per_physical_unit).sort().map((unit) => <option key={unit} value={unit}>{unit}</option>)}
            </select>
            <span className={`inline-block rounded border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wide ${unitFilter ? 'border-amber-800 bg-amber-950/40 text-amber-300' : 'border-emerald-800 bg-emerald-950/40 text-emerald-300'}`}>
              {unitFilter ? 'FILTERED EXPLORATORY VIEW' : 'CANONICAL'}
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Histograma: bursts candidatos / capture</div>
              <HistogramChart values={Object.values(filtered ? filtered.candidate : summary.candidate_bursts_per_capture)} xLabel="bursts candidatos" noDataReason="Sin burst_records reales todavia (o la unidad filtrada no tiene capturas)." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Histograma: bursts CRC-validos / capture</div>
              <HistogramChart values={Object.values(filtered ? filtered.crcValid : summary.crc_valid_per_capture)} xLabel="bursts CRC-validos" noDataReason="Sin bursts CRC-validos reales todavia (o la unidad filtrada no tiene capturas)." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">Histograma: bursts admitidos (packet_eligible) / capture</div>
              <HistogramChart values={Object.values(filtered ? filtered.admitted : summary.admitted_per_capture)} xLabel="bursts admitidos" noDataReason="Sin bursts admitidos reales todavia (o la unidad filtrada no tiene capturas)." />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">ECDF: bursts elegibles / ventana (siempre canonico -- sin mapeo ventana-&gt;unidad real todavia)</div>
              <EcdfChart values={Object.values(summary.eligible_bursts_per_window)} xLabel="bursts elegibles" noDataReason="Sin decision_window_records reales todavia." />
            </div>
          </div>

          <div className="text-[11px] text-slate-500">
            Capturas con discontinuidades reales (discontinuity_count &gt; 0): <span className="font-mono text-slate-300">{summary.captures_with_discontinuities}</span>
            {' '}-- deviations registradas para este run: <span className="font-mono text-slate-300">{summary.deviation_count}</span>
          </div>
        </>
      )}
    </div>
  );
}
