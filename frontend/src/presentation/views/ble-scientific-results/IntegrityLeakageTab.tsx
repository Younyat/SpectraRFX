import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, ScientificBurstRecord, ScientificCaptureRecord, ScientificDecisionWindowRecord } from '../../../app/services/bleScientificResultsApi';
import RunPickerBar from './RunPickerBar';
import { useRunRecords } from './useRunRecords';

const sciApi = new BleScientificResultsApiService();

export default function IntegrityLeakageTab() {
  const { runs, paperRunId, setPaperRunId, status, building, buildRecords, error } = useRunRecords();
  const [captures, setCaptures] = useState<ScientificCaptureRecord[]>([]);
  const [selectedCapture, setSelectedCapture] = useState<string | null>(null);
  const [bursts, setBursts] = useState<ScientificBurstRecord[]>([]);
  const [windows, setWindows] = useState<ScientificDecisionWindowRecord[]>([]);

  useEffect(() => {
    if (!paperRunId || !status?.built) {
      setCaptures([]);
      setSelectedCapture(null);
      return;
    }
    sciApi.captures(paperRunId, 200, 0).then(setCaptures).catch(() => setCaptures([]));
  }, [paperRunId, status?.built]);

  useEffect(() => {
    if (!paperRunId || !selectedCapture) {
      setBursts([]);
      setWindows([]);
      return;
    }
    sciApi.bursts(paperRunId, 100, 0, selectedCapture).then(setBursts).catch(() => setBursts([]));
    sciApi.windows(paperRunId, 100, 0, selectedCapture).then(setWindows).catch(() => setWindows([]));
  }, [paperRunId, selectedCapture]);

  const included = captures.filter((c) => c.eligible);
  const excluded = captures.filter((c) => !c.eligible);

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Integrity and Leakage</div>
        <div className="mt-1 text-xs text-slate-500">
          Navegacion capture -&gt; burst -&gt; decision window, con incluidos/excluidos/motivo siempre visibles. Solo
          lectura -- ningun registro cientifico es editable desde esta interfaz.
        </div>
      </div>

      <RunPickerBar runs={runs} paperRunId={paperRunId} setPaperRunId={setPaperRunId} status={status} building={building} buildRecords={buildRecords} error={error} />

      {captures.length > 0 && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded border border-emerald-800 bg-emerald-950/20 px-3 py-2">
            <div className="text-emerald-400">Incluidas</div>
            <div className="font-mono text-lg text-emerald-200">{included.length}</div>
          </div>
          <div className="rounded border border-amber-800 bg-amber-950/20 px-3 py-2">
            <div className="text-amber-400">Excluidas</div>
            <div className="font-mono text-lg text-amber-200">{excluded.length}</div>
          </div>
        </div>
      )}

      {captures.length > 0 && (
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="text-slate-500">
            <tr><th className="py-1 pr-3">capture_id</th><th className="py-1 pr-3">split</th><th className="py-1 pr-3">eligible</th><th className="py-1 pr-3">exclusion_reason_codes</th><th className="py-1"></th></tr>
          </thead>
          <tbody>
            {captures.map((capture) => (
              <tr key={capture.capture_id} className={`cursor-pointer border-t border-slate-800 hover:bg-slate-900/40 ${selectedCapture === capture.capture_id ? 'bg-slate-900/60' : ''}`} onClick={() => setSelectedCapture(capture.capture_id)}>
                <td className="py-1 pr-3 font-mono">{capture.capture_id}</td>
                <td className="py-1 pr-3">{capture.split ?? '(sin asignar)'}</td>
                <td className="py-1 pr-3">{capture.eligible ? 'si' : 'no'}</td>
                <td className="py-1 pr-3">{capture.exclusion_reason_codes.join(', ') || '-'}</td>
                <td className="py-1 text-cyan-400">ver bursts/ventanas</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selectedCapture && (
        <div className="space-y-3">
          <div className="text-xs font-semibold text-slate-400">Bursts de {selectedCapture} ({bursts.length})</div>
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr><th className="py-1 pr-3">burst_id</th><th className="py-1 pr-3">burst_class</th><th className="py-1 pr-3">crc_status</th><th className="py-1 pr-3">association_status</th><th className="py-1 pr-3">eligible</th><th className="py-1">exclusion_reason_codes</th></tr>
            </thead>
            <tbody>
              {bursts.map((burst) => (
                <tr key={burst.burst_id} className="border-t border-slate-800">
                  <td className="py-1 pr-3 font-mono">{burst.burst_id}</td>
                  <td className="py-1 pr-3">{burst.burst_class}</td>
                  <td className="py-1 pr-3">{burst.crc_status ?? '-'}</td>
                  <td className="py-1 pr-3">{burst.association_status ?? '-'}</td>
                  <td className="py-1 pr-3">{burst.eligible ? 'si' : 'no'}</td>
                  <td className="py-1">{burst.exclusion_reason_codes.join(', ') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="text-xs font-semibold text-slate-400">Decision windows ({windows.length})</div>
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr><th className="py-1 pr-3">decision_window_id</th><th className="py-1 pr-3">active</th><th className="py-1 pr-3">eligible_burst_count</th><th className="py-1 pr-3">decision_eligible</th><th className="py-1">ineligibility_reason_codes</th></tr>
            </thead>
            <tbody>
              {windows.map((window) => (
                <tr key={window.decision_window_id} className="border-t border-slate-800">
                  <td className="py-1 pr-3 font-mono">{window.decision_window_id}</td>
                  <td className="py-1 pr-3">{window.active ? 'si' : 'no'}</td>
                  <td className="py-1 pr-3">{window.eligible_burst_count}</td>
                  <td className="py-1 pr-3">{window.decision_eligible ? 'si' : 'no'}</td>
                  <td className="py-1">{window.ineligibility_reason_codes.join(', ') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
