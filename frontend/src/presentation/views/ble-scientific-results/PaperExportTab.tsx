import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, NoDataResponse, PaperExportManifest } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

function isNoData(manifest: unknown): manifest is NoDataResponse {
  return !!manifest && (manifest as NoDataResponse).status === 'NO_DATA';
}

export default function PaperExportTab() {
  const [manifest, setManifest] = useState<PaperExportManifest | NoDataResponse | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    sciApi.getPaperExportManifest().then(setManifest).catch(() => setManifest({ status: 'NO_DATA' }));
  }, []);

  const generate = async () => {
    setBusy(true);
    try {
      const result = await sciApi.runPaperExport();
      setManifest(result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Paper export</div>
        <div className="mt-1 text-xs text-slate-500">
          Genera <code>paper_exports/</code> a partir de artefactos canonicos reales unicamente. study_status.json y
          paper_readiness.json siempre se generan de verdad; todo lo demas (CSVs de RQ1-4, tablas LaTeX, figuras)
          queda SKIPPED_NO_DATA hasta que exista una campana real -- nunca una fila o figura inventada.
        </div>
      </div>

      <button
        className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy}
        onClick={generate}
      >
        {busy ? 'Generando...' : 'Generar exports'}
      </button>

      {(!manifest || isNoData(manifest)) && <NoDataNotice reason="Ningun export se ha generado todavia en esta sesion del repositorio." />}

      {manifest && !isNoData(manifest) && (
        <>
          <div className="text-xs text-slate-400">
            {manifest.generated_count} generado(s) real(es), {manifest.skipped_count} SKIPPED_NO_DATA -- generated_at: {manifest.generated_at}
          </div>
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr><th className="py-1 pr-3">File</th><th className="py-1 pr-3">Status</th><th className="py-1">Detail</th></tr>
            </thead>
            <tbody>
              {manifest.entries.map((entry) => (
                <tr key={entry.file} className="border-t border-slate-800">
                  <td className="py-1 pr-3 font-mono">{entry.file}</td>
                  <td className="py-1 pr-3"><StatusBadge status={entry.status} /></td>
                  <td className="py-1 text-slate-500">{entry.detail ?? entry.would_be_derived_from ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
