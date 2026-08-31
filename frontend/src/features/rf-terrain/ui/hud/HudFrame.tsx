import React from 'react';
import { HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND, HUD_ACCENT_BRIGHT } from './hudTheme';

interface HudFrameProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

// Glass instrument-panel frame reused by every floating window in this
// module (Menu/Layers, Receiver, Pan, Profiles, Inspector, Legend): a dark
// cyan-tinted glass background, a soft cyan glow border, and four small
// corner brackets -- the "cockpit HUD" cue -- as a purely decorative
// overlay (never clips content), so panels that scroll internally
// (Inspector, Profiles) are unaffected.
export const HudFrame: React.FC<HudFrameProps> = ({ children, className = '', style }) => (
  <div
    className={`relative ${className}`}
    style={{
      background: HUD_PANEL_BACKGROUND,
      border: `1px solid ${HUD_BORDER_COLOR}`,
      boxShadow: HUD_GLOW_SHADOW,
      backdropFilter: 'blur(14px)',
      WebkitBackdropFilter: 'blur(14px)',
      ...style,
    }}
  >
    <HudCorner position="top-left" />
    <HudCorner position="top-right" />
    <HudCorner position="bottom-left" />
    <HudCorner position="bottom-right" />
    {children}
  </div>
);

const CORNER_STYLE: Record<string, React.CSSProperties> = {
  'top-left': { left: -1, top: -1, borderLeftWidth: 2, borderTopWidth: 2 },
  'top-right': { right: -1, top: -1, borderRightWidth: 2, borderTopWidth: 2 },
  'bottom-left': { left: -1, bottom: -1, borderLeftWidth: 2, borderBottomWidth: 2 },
  'bottom-right': { right: -1, bottom: -1, borderRightWidth: 2, borderBottomWidth: 2 },
};

const HudCorner: React.FC<{ position: keyof typeof CORNER_STYLE }> = ({ position }) => (
  <span
    className="pointer-events-none absolute h-3 w-3 border-solid"
    style={{ borderColor: HUD_ACCENT_BRIGHT, ...CORNER_STYLE[position] }}
  />
);
