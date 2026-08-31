import React from 'react';
import type { EpistemicStatus } from '../model/rfTerrainTypes';

// Zero-tolerance semantic rule: a HYPOTHESIS must never render with the
// same wording/weight as MEASURED or EVIDENCE. Color + label together,
// never color alone -- both survive a grayscale screenshot or a color-
// vision-deficient reader.
const STYLE: Record<EpistemicStatus, { bg: string; fg: string; border: string }> = {
  MEASURED: { bg: 'rgba(74,222,128,0.12)', fg: '#4ade80', border: '#4ade80' },
  DERIVED: { bg: 'rgba(56,189,248,0.12)', fg: '#38bdf8', border: '#38bdf8' },
  HYPOTHESIS: { bg: 'rgba(251,191,36,0.12)', fg: '#fbbf24', border: '#fbbf24' },
  EVIDENCE: { bg: 'rgba(203,213,225,0.12)', fg: '#cbd5e1', border: '#cbd5e1' },
  SIMULATED: { bg: 'rgba(167,139,250,0.12)', fg: '#a78bfa', border: '#a78bfa' },
};

export const EpistemicTag: React.FC<{ status: EpistemicStatus }> = ({ status }) => {
  const style = STYLE[status];
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide"
      style={{ background: style.bg, color: style.fg, border: `1px solid ${style.border}` }}
    >
      {status}
    </span>
  );
};
