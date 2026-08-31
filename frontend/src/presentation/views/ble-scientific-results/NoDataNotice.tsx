/** Shown whenever a canonical artifact does not exist on disk yet -- never
 * a blank panel, never a 0, never a placeholder number. `reason` names the
 * real artifact this panel is waiting for, so the honest gap is
 * self-explanatory rather than looking like a bug. */
export default function NoDataNotice({ reason }: { reason: string }) {
  return (
    <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center">
      <div className="text-sm font-semibold tracking-wide text-slate-400">NO DATA</div>
      <div className="mt-1 text-xs text-slate-500">{reason}</div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Record<string, string> = {
    READY: 'bg-emerald-900/40 text-emerald-300 border-emerald-800',
    COMPLETE: 'bg-emerald-900/40 text-emerald-300 border-emerald-800',
    FROZEN: 'bg-emerald-900/40 text-emerald-300 border-emerald-800',
    PRELIMINARY: 'bg-amber-900/40 text-amber-300 border-amber-800',
    IN_PROGRESS: 'bg-amber-900/40 text-amber-300 border-amber-800',
    SCIENTIST_DECISION_REQUIRED: 'bg-amber-900/40 text-amber-300 border-amber-800',
    INCOMPLETE: 'bg-amber-900/40 text-amber-300 border-amber-800',
    BLOCKED: 'bg-red-900/40 text-red-300 border-red-800',
    INVALIDATED: 'bg-red-900/40 text-red-300 border-red-800',
    NOT_READY: 'bg-red-900/40 text-red-300 border-red-800',
    OPENED: 'bg-red-900/40 text-red-300 border-red-800',
    DATA_PENDING: 'bg-slate-800 text-slate-400 border-slate-700',
    NO_DATA: 'bg-slate-800 text-slate-400 border-slate-700',
    NOT_STARTED: 'bg-slate-800 text-slate-400 border-slate-700',
    NONE: 'bg-slate-800 text-slate-400 border-slate-700',
    UNTOUCHED: 'bg-emerald-900/40 text-emerald-300 border-emerald-800',
    NOT_APPLICABLE: 'bg-slate-800 text-slate-400 border-slate-700',
    // Scientific completeness report vocabulary (2026-08-17).
    AVAILABLE: 'bg-emerald-900/40 text-emerald-300 border-emerald-800',
    PENDING_REAL_ACQUISITION: 'bg-amber-900/40 text-amber-300 border-amber-800',
    NOT_ELIGIBLE: 'bg-slate-800 text-slate-400 border-slate-700',
    PROTECTED: 'bg-cyan-900/40 text-cyan-300 border-cyan-800',
  };
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-[11px] font-mono ${tone[status] ?? 'bg-slate-800 text-slate-400 border-slate-700'}`}>
      {status}
    </span>
  );
}
