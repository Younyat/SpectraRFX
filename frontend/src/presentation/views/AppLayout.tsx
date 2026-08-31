import React from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Loader2, RadioTower } from 'lucide-react';
import { useAppActions, useGlobalActivity, useUiState } from '../../app/store/AppStore';
import { cn } from '../../shared/utils';
import { findModuleByPath, navigationModules } from '../../app/modules/labModules';

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const ui = useUiState();
  const globalActivity = useGlobalActivity();
  const { setUiState } = useAppActions();

  // overflow-hidden as a hard backstop: with every child column below now
  // properly min-h-0-constrained, nothing should overflow this box -- but
  // pinning it here too guarantees the whole page can never grow past
  // exactly one viewport, no matter what content is mounted through the
  // router below.
  return (
    <div className="app-shell flex h-screen overflow-hidden">
      {/* Sidebar */}
      {/* min-h-0 (both here and on the h-full wrapper + nav below) is
          required: without it, this column's own min-height:auto default
          refuses to shrink below the FULL height of every nav link listed
          below (there are a lot of modules), so a long module list was
          silently stretching this entire flex row -- and therefore the
          whole page, since overflow-visible is deliberately kept for the
          collapse toggle button -- taller than h-screen. That's what showed
          as dead space (or the OS desktop) below the fold. */}
      <div className={cn(
        "app-sidebar relative flex min-h-0 flex-col border-r shadow-2xl transition-all duration-300 overflow-visible",
        ui.sidebarCollapsed ? "w-0" : "w-64"
      )}>
        {/* Collapse / expand toggle — pinned to the right edge of the sidebar, always visible */}
        <button
          onClick={() => setUiState({ sidebarCollapsed: !ui.sidebarCollapsed })}
          title={ui.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="absolute -right-3 top-5 z-30 flex h-6 w-6 items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-slate-300 shadow-md hover:bg-slate-600 hover:text-white transition-colors"
        >
          {ui.sidebarCollapsed
            ? <ChevronRight className="w-3 h-3" />
            : <ChevronLeft className="w-3 h-3" />}
        </button>

        {/* Sidebar content — hidden when collapsed */}
        <div className={cn('flex min-h-0 flex-col h-full transition-opacity duration-200', ui.sidebarCollapsed ? 'opacity-0 pointer-events-none invisible' : 'opacity-100 visible')}>
          {/* Header */}
          <div className="border-b p-4 flex-shrink-0" style={{ borderColor: 'var(--app-sidebar-border)' }}>
            <div className="flex items-center gap-3">
              <img src="/logo-mark.png" alt="" className="h-9 w-9 flex-shrink-0" />
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em]" style={{ color: 'var(--app-accent)' }}>RF Research Platform</div>
                <h1 className="text-xl font-bold">SpectraRF<sup>x</sup></h1>
              </div>
            </div>
          </div>

          {/* Navigation -- scrolls internally (min-h-0 + overflow-y-auto) so
              a long module list never grows this column past h-screen. */}
          <nav className="flex-1 min-h-0 overflow-y-auto p-4 space-y-2">
            {navigationModules.map((item) => {
              const isActive = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`) || (item.aliases ?? []).includes(location.pathname);
              return (
                <Link
                  key={item.id}
                  to={item.path}
                  className={cn(
                    "flex items-center rounded-2xl px-3 py-2 text-sm font-medium transition-colors",
                    isActive ? "bg-amber-300 text-slate-950" : "hover:bg-white/5"
                  )}
                  style={isActive ? { background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' } : { color: 'var(--app-sidebar-text)' }}
                >
                  <item.icon className="w-5 h-5 mr-3 flex-shrink-0" />
                  {item.name}
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="border-t p-4 flex-shrink-0" style={{ borderColor: 'var(--app-sidebar-border)' }}>
            <div className="text-xs" style={{ color: 'var(--app-sidebar-muted)' }}>
              Acquisition + Dataset + QC
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden app-shell">
        {globalActivity?.visible && (
          <div className="pointer-events-none fixed bottom-6 right-6 z-50 max-w-[calc(100vw-2rem)]">
            <div
              className="w-[min(28rem,calc(100vw-2rem))] overflow-hidden rounded-[1.35rem] border border-white/20 text-white shadow-[0_22px_70px_rgba(15,23,42,0.30)] backdrop-blur-2xl"
              style={{ background: 'linear-gradient(135deg, rgba(15,23,42,0.78), rgba(30,41,59,0.56))' }}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-white/15 bg-white/10">
                  {globalActivity.kind === 'capturing' ? (
                    <RadioTower className="h-5 w-5 animate-pulse text-emerald-300" />
                  ) : (
                    <Loader2 className="h-5 w-5 animate-spin text-amber-300" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.85)]" />
                    <span className="truncate">{globalActivity.title}</span>
                  </div>
                  {globalActivity.phase&&<div className="mt-1 text-xs font-medium text-sky-200">{globalActivity.phase}{globalActivity.progressPercent!=null?` · ${globalActivity.progressPercent}%`:''}</div>}
                  {globalActivity.detail && <div className="mt-1 text-xs text-slate-200/90">{globalActivity.detail}</div>}
                  <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-slate-300">{globalActivity.target&&<span>Objetivo: {globalActivity.target}</span>}{globalActivity.configuredDurationSeconds!=null&&<span>Captura: {globalActivity.configuredDurationSeconds}s</span>}{globalActivity.elapsedSeconds!=null&&<span>Transcurrido: {globalActivity.elapsedSeconds}s</span>}{globalActivity.estimatedRemainingSeconds!=null&&<span>Restante aprox.: {globalActivity.estimatedRemainingSeconds}s</span>}{globalActivity.totalItems!=null&&<span>{globalActivity.processedItems??0}/{globalActivity.totalItems}</span>}</div>
                </div>
              </div>
              <div className="h-1 overflow-hidden bg-white/10">
                <div className={`h-full rounded-full bg-gradient-to-r from-amber-300 via-emerald-300 to-sky-300 transition-all ${globalActivity.progressPercent==null?'w-1/2 animate-[pulse_1.4s_ease-in-out_infinite]':''}`} style={globalActivity.progressPercent==null?undefined:{width:`${globalActivity.progressPercent}%`}} />
              </div>
            </div>
          </div>
        )}

        {/* Top bar */}
        <div className="relative flex-shrink-0">
          <div
            className="overflow-hidden transition-all duration-300"
            style={{ maxHeight: ui.topBarCollapsed ? '0px' : '160px' }}
          >
            <header className="app-surface border-b px-6 py-4 shadow-sm backdrop-blur">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">
                  {findModuleByPath(location.pathname)?.name || 'SpectraRFˣ'}
                </h2>
                <div className="flex items-center space-x-4">
                  <select
                    value={ui.theme}
                    onChange={(event) => setUiState({ theme: event.target.value as typeof ui.theme })}
                    className="rounded-full border px-3 py-2 text-sm"
                    style={{ background: 'var(--app-surface-strong)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
                  >
                    <option value="light">White</option>
                    <option value="dark">Dark</option>
                    <option value="laboratory">Laboratory</option>
                  </select>
                  {/* Status indicator */}
                  <div className="flex items-center space-x-2">
                    <div className="h-2 w-2 rounded-full bg-emerald-500"></div>
                    <span className="text-sm app-muted-text">Backend compartido activo</span>
                  </div>
                </div>
              </div>
            </header>
          </div>
          {/* Collapse / expand toggle — pinned to the bottom edge of the top bar, always visible */}
          <button
            onClick={() => setUiState({ topBarCollapsed: !ui.topBarCollapsed })}
            title={ui.topBarCollapsed ? 'Show top bar' : 'Hide top bar'}
            className="absolute -bottom-3 left-1/2 z-30 flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-slate-300 shadow-md transition-colors hover:bg-slate-600 hover:text-white"
          >
            {ui.topBarCollapsed ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
          </button>
        </div>

        {/* Page content */}
        {/* min-h-0 is required here: without it, a flex item defaults to
            min-height:auto, which refuses to shrink below its content's
            intrinsic size -- so this container could render taller than the
            viewport space flex-1 actually allocated it, leaving dead space
            below whatever page is mounted (e.g. Live Monitor's spectrum)
            visible only by scrolling. overflow-auto then correctly scrolls
            WITHIN the allocated space instead of the space itself growing. */}
        <main className="flex-1 min-h-0 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
