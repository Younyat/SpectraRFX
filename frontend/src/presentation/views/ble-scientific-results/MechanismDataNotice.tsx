import { StatusBadge } from './NoDataNotice';

/** Paper progress dashboard, point 5 (2026-08-11): every panel must report
 * MECHANISM and DATA as two independent states -- NO_DATA must never read
 * as "the functionality isn't built yet". `mechanism` is always READY once
 * the renderer/backend/schema/export code for this panel exists and is
 * tested (regardless of whether real data exists); `dataReason` explains,
 * honestly, why DATA is still NO_DATA (e.g. no real campaign yet, or -- for
 * RQ2 -- that no canonical per-branch producer exists at all today). */
export default function MechanismDataNotice({ data = 'NO_DATA', dataReason }: { data?: 'NO_DATA' | 'AVAILABLE'; dataReason: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs">
      <span className="text-slate-500">MECHANISM</span>
      <StatusBadge status="READY" />
      <span className="text-slate-500">DATA</span>
      <StatusBadge status={data === 'AVAILABLE' ? 'COMPLETE' : 'NO_DATA'} />
      <span className="text-slate-500">{dataReason}</span>
    </div>
  );
}
