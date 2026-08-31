import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, QualitySummaryResponse, RunArtifactsResponse } from '../../../app/services/bleScientificResultsApi';
import RunPickerBar from './RunPickerBar';
import { useRunRecords } from './useRunRecords';

const sciApi = new BleScientificResultsApiService();

export default function AcquisitionQualityTab() {
  const { runs, paperRunId, setPaperRunId, status, building, buildRecords, error } = useRunRecords();
  const [quality, setQuality] = useState<QualitySummaryResponse | null>(null);
  const [artifacts, setArtifacts] = useState<RunArtifactsResponse | null>(null);

  useEffect(() => {
    if (!paperRunId || !status?.built) {
      setQuality(null);
      setArtifacts(null);
      return;
    }
    sciApi.qualitySummary(paperRunId).then(setQuality).catch(() => setQuality(null));
    sciApi.artifacts(paperRunId).then(setArtifacts).catch(() => setArtifacts(null));
  }, [paperRunId, status?.built]);

  const figureFiles = (artifacts?.files ?? []).filter((f) => f.startsWith('07_figures/'));

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Acquisition Quality</div>
        <div className="mt-1 text-xs text-slate-500">
          Resumenes puramente descriptivos (count/mean/median/std/min/max/cuartiles/missing) -- sin intervalos de
          confianza ni p-values, eso llega en una fase posterior. Campos sin fuente real (SNR, orden de adquisicion)
          se muestran honestamente vacios, nunca inventados.
        </div>
      </div>

      <RunPickerBar runs={runs} paperRunId={paperRunId} setPaperRunId={setPaperRunId} status={status} building={building} buildRecords={buildRecords} error={error} />

      {quality && quality.association_summary.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Association summary</div>
          <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            {Object.entries(quality.association_summary[0]).map(([key, value]) => (
              <div key={key} className="rounded border border-slate-700 bg-slate-900/60 px-2 py-1.5">
                <div className="text-slate-500">{key}</div>
                <div className="font-mono text-slate-200">{typeof value === 'number' ? value.toFixed(4) : String(value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {quality && quality.capture_field_summary.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Capture field summary ({quality.capture_field_summary.length} filas)</div>
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-left text-[11px] text-slate-300">
              <thead className="sticky top-0 bg-slate-950 text-slate-500">
                <tr>
                  <th className="py-1 pr-2">physical_unit_id</th><th className="py-1 pr-2">channel</th><th className="py-1 pr-2">field</th>
                  <th className="py-1 pr-2">n</th><th className="py-1 pr-2">missing</th><th className="py-1 pr-2">mean</th><th className="py-1">std</th>
                </tr>
              </thead>
              <tbody>
                {quality.capture_field_summary.map((row, index) => (
                  <tr key={index} className="border-t border-slate-800">
                    <td className="py-1 pr-2 font-mono">{String(row.physical_unit_id ?? '-')}</td>
                    <td className="py-1 pr-2">{String(row.channel ?? '-')}</td>
                    <td className="py-1 pr-2">{String(row.field)}</td>
                    <td className="py-1 pr-2">{String(row.n)}</td>
                    <td className="py-1 pr-2">{String(row.missing_count)}</td>
                    <td className="py-1 pr-2">{row.mean === null ? 'NOT_DOCUMENTED' : Number(row.mean).toFixed(2)}</td>
                    <td className="py-1">{row.std === null ? '-' : Number(row.std).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {figureFiles.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Figuras generadas ({figureFiles.length})</div>
          <ul className="grid grid-cols-2 gap-1 text-[11px] text-slate-400 md:grid-cols-4">
            {figureFiles.map((file) => <li key={file} className="truncate rounded border border-slate-800 px-2 py-1 font-mono" title={file}>{file.replace('07_figures/', '')}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
