import { useEffect, useState } from 'react';
import { BleScientificResultsApiService, NoDataResponse } from '../../../app/services/bleScientificResultsApi';
import NoDataNotice, { StatusBadge } from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();

interface QualificationItem { status: string; detail?: unknown }
interface QualificationReport {
  schema_version: string;
  generated_at: string;
  overall_status: string;
  required_gates: string[];
  reasons: string[];
  items: Record<string, QualificationItem>;
}

function isNoData(report: unknown): report is NoDataResponse {
  return !!report && (report as NoDataResponse).status === 'NO_DATA';
}

export default function QualificationTab() {
  const [report, setReport] = useState<QualificationReport | NoDataResponse | null>(null);

  useEffect(() => {
    sciApi.campaignQualificationPreflightLatest().then(setReport as never).catch(() => setReport({ status: 'NO_DATA' }));
  }, []);

  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Hardware &amp; qualification</div>
        <div className="mt-1 text-xs text-slate-500">
          run_campaign_qualification_preflight() -- un gate NOT_CHECKED requerido nunca produce READY, solo
          PRELIMINARY o NOT_READY.
        </div>
      </div>

      {(!report || isNoData(report)) && <NoDataNotice reason="Ningun campaign_qualification_preflight_report.json existe todavia -- ninguna verificacion de hardware se ha ejecutado." />}

      {report && !isNoData(report) && (
        <>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-400">Overall:</span>
            <StatusBadge status={report.overall_status} />
          </div>
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr><th className="py-1 pr-3">Gate</th><th className="py-1 pr-3">Status</th><th className="py-1">Detail</th></tr>
            </thead>
            <tbody>
              {report.required_gates.map((gate) => (
                <tr key={gate} className="border-t border-slate-800">
                  <td className="py-1 pr-3 font-mono">{gate}</td>
                  <td className="py-1 pr-3"><StatusBadge status={report.items[gate]?.status ?? 'NOT_CHECKED'} /></td>
                  <td className="py-1 text-slate-500">{String(report.items[gate]?.detail ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
