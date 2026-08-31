export type EvidenceMaturity = 'QUALIFICATION' | 'DEVELOPMENT' | 'VALIDATION' | 'CONFIRMATORY' | 'ENGINEERING';

const TONE: Record<EvidenceMaturity, string> = {
  QUALIFICATION: 'bg-slate-800 text-slate-400 border-slate-700',
  DEVELOPMENT: 'bg-sky-950/40 text-sky-300 border-sky-800',
  VALIDATION: 'bg-amber-950/40 text-amber-300 border-amber-800',
  CONFIRMATORY: 'bg-emerald-950/40 text-emerald-300 border-emerald-800',
  ENGINEERING: 'bg-violet-950/40 text-violet-300 border-violet-800',
};

/** Every figure/table must declare which evidence tier backs it -- a
 * VALIDATION result must never visually resemble a CONFIRMATORY one. Pure
 * label renderer: the maturity value itself always comes from the caller
 * (which artifact/report the data was actually read from), never guessed
 * here. */
export default function EvidenceMaturityBadge({ maturity }: { maturity: EvidenceMaturity }) {
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wide ${TONE[maturity]}`}>
      {maturity}
    </span>
  );
}
