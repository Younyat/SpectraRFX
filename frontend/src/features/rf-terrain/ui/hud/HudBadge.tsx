import React from 'react';
import { HUD_ACCENT, HUD_BADGE_BACKGROUND, HUD_BORDER_COLOR, hudLabelClass } from './hudTheme';

interface HudBadgeProps {
  label: string;
  value: string;
  accent?: string;
}

// Small angular glass pill (clipped corners, not rounded) for a single
// real readout -- the floating "FREQUENCY / TIME / POWER" row over
// the canvas. Every value passed in must already be real; this component
// never invents a placeholder number, only formats what it's given (an
// em dash upstream when nothing real is available yet).
//
// Deliberately lighter/more transparent than every other HUD panel
// (HUD_BADGE_BACKGROUND, not HUD_PANEL_BACKGROUND): this one sits directly
// over the live terrain, which can rise tall right behind it -- a near-
// solid backing plate here would hide exactly the signal it's labeling.
// A light blur plus a real text-shadow keeps the numbers legible without
// needing an opaque background.
export const HudBadge: React.FC<HudBadgeProps> = ({ label, value, accent = HUD_ACCENT }) => (
  <div
    className="pointer-events-none flex flex-col items-center gap-0.5 px-4 py-1.5"
    style={{
      background: HUD_BADGE_BACKGROUND,
      border: `1px solid ${HUD_BORDER_COLOR}`,
      backdropFilter: 'blur(6px)',
      WebkitBackdropFilter: 'blur(6px)',
      clipPath: 'polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%)',
    }}
  >
    <span className={hudLabelClass} style={{ color: accent, textShadow: '0 1px 4px rgba(0,0,0,0.9)' }}>{label}</span>
    <span className="font-mono text-sm tabular-nums text-slate-50" style={{ textShadow: '0 1px 4px rgba(0,0,0,0.9)' }}>{value}</span>
  </div>
);
