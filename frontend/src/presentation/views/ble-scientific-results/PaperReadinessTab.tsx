import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, PaperReadinessRow } from '../../../app/services/bleScientificResultsApi';
import { StatusBadge } from './NoDataNotice';
import EvidenceMaturityBadge, { EvidenceMaturity } from './EvidenceMaturityBadge';

const sciApi = new BleScientificResultsApiService();

/** Fast-closure pass (2026-08-12): rewritten to the exact 8-column / 16-row
 * taxonomy requested for paper closure -- manuscript_element,
 * scientific_mechanism, evidence_maturity, canonical_artifact,
 * statistics_ready, table_ready, figure_ready, paper_evidence_status.
 * Pure read of get_paper_readiness()'s real, already-computed fields --
 * nothing derived in the frontend. */
export default function PaperReadinessTab() {
  const [rows, setRows] = useState<PaperReadinessRow[] | null>(null);

  useEffect(() => {
    sciApi.paperReadiness().then(setRows).catch(() => setRows(null));
  }, []);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Paper readiness</div>
        <div className="mt-1 text-xs text-slate-500">
          Un elemento del manuscrito solo se marca disponible cuando su artefacto canonico real existe en disco; solo
          se marca confirmatorio (evidence_maturity=CONFIRMATORY) cuando ademas hay un protocol freeze real (nunca a
          partir de un VALIDATION_DRY_RUN).
        </div>
      </div>

      {rows && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr>
                <th className="py-1 pr-3">Manuscript element</th>
                <th className="py-1 pr-3">Scientific mechanism</th>
                <th className="py-1 pr-3">Evidence maturity</th>
                <th className="py-1 pr-3">Canonical artifact</th>
                <th className="py-1 pr-3">Stats</th>
                <th className="py-1 pr-3">Table</th>
                <th className="py-1 pr-3">Figure</th>
                <th className="py-1">Evidence status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.manuscript_element} className="border-t border-slate-800">
                  <td className="py-1.5 pr-3 font-medium text-slate-200">{row.manuscript_element}</td>
                  <td className="py-1.5 pr-3 font-mono text-[11px] text-slate-500">{row.scientific_mechanism}</td>
                  <td className="py-1.5 pr-3">
                    {row.evidence_maturity ? <EvidenceMaturityBadge maturity={row.evidence_maturity as EvidenceMaturity} /> : <span className="text-slate-600">N/A</span>}
                  </td>
                  <td className="py-1.5 pr-3 font-mono text-[11px] text-slate-500">{row.canonical_artifact}</td>
                  <td className="py-1.5 pr-3">{row.statistics_ready ? 'YES' : 'NO'}</td>
                  <td className="py-1.5 pr-3">{row.table_ready ? 'YES' : 'NO'}</td>
                  <td className="py-1.5 pr-3">{row.figure_ready ? 'YES' : 'NO'}</td>
                  <td className="py-1.5"><StatusBadge status={row.paper_evidence_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
