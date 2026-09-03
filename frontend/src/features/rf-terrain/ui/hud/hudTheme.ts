// Shared cinematic-cockpit HUD visual language for RF Terrain 3D's
// floating panels -- scoped entirely to this module (never touches the
// platform-wide `--app-border`/`app-muted-text` theme vars other views
// depend on). Presentation only: nothing here changes what data any
// panel shows, only how it is framed.
export const HUD_PANEL_BACKGROUND = 'linear-gradient(165deg, rgba(9,22,35,0.82), rgba(3,9,16,0.72))';
// Lighter variant for chrome that sits directly OVER the live terrain
// (the floating frequency/time/power badges) -- readable text without a
// near-solid backing plate hiding the peaks rising up behind it.
export const HUD_BADGE_BACKGROUND = 'linear-gradient(165deg, rgba(9,22,35,0.32), rgba(3,9,16,0.22))';
export const HUD_BORDER_COLOR = 'rgba(94,234,212,0.30)';
export const HUD_GLOW_SHADOW = '0 0 24px rgba(45,212,191,0.14), inset 0 1px 0 rgba(165,243,252,0.08)';
export const HUD_ACCENT = '#5eead4';
export const HUD_ACCENT_BRIGHT = '#67e8f9';
export const HUD_TEXT_DIM = 'rgba(186,230,253,0.55)';
// A solid (non-gradient, non-transparent) fallback for native controls whose
// dropdown/option popup a browser renders outside this panel's own stacking
// context -- a `<select>` styled with only a transparent/gradient background
// still lets its native OS option list fall back to a light system default
// while inheriting this panel's light text color, producing unreadable
// near-white-on-white text. Real bug, not hypothetical: reported against
// the FSEI -- AI Model Inspection panel's model pickers.
export const HUD_SOLID_INPUT_BACKGROUND = '#071620';

export const hudLabelClass = 'text-[9px] font-semibold uppercase tracking-[0.18em]';
