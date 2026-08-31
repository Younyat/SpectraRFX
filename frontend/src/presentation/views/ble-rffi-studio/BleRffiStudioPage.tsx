import { useState } from 'react';
import BleRffiStudioGuided from './BleRffiStudioGuided';
import BleRffiStudioDashboard from './BleRffiStudioDashboard';

type Mode = 'guided' | 'advanced';

export default function BleRffiStudioPage() {
  const [mode, setMode] = useState<Mode>('guided');

  return (
    <div>
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-4 py-2 backdrop-blur">
        <div>
          <div className="text-base font-bold text-slate-100">BLE-RFFI End-to-End Studio</div>
          <div className="text-xs text-slate-500">Captura -&gt; evidencia -&gt; dataset -&gt; entrenamiento -&gt; evaluacion -&gt; exportacion -&gt; inferencia offline</div>
        </div>
        <div className="flex rounded-md border border-slate-700 p-0.5 text-sm">
          <button
            className={`rounded px-3 py-1.5 transition-colors ${mode === 'guided' ? 'bg-cyan-600/30 text-cyan-100' : 'text-slate-400 hover:bg-slate-800'}`}
            onClick={() => setMode('guided')}
          >
            Modo guiado
          </button>
          <button
            className={`rounded px-3 py-1.5 transition-colors ${mode === 'advanced' ? 'bg-cyan-600/30 text-cyan-100' : 'text-slate-400 hover:bg-slate-800'}`}
            onClick={() => setMode('advanced')}
          >
            Modo avanzado
          </button>
        </div>
      </div>
      {/* Guided stays mounted even while Advanced is shown -- switching
          modes must never lose an in-progress campaign session or its job
          polling. Advanced stays conditionally mounted (as before): it has
          no equivalent long-running local state to lose, and keeping both
          dashboards alive at once would double up their background polling
          for no benefit. */}
      <div style={{ display: mode === 'guided' ? 'block' : 'none' }}>
        <BleRffiStudioGuided />
      </div>
      {mode === 'advanced' && <BleRffiStudioDashboard />}
    </div>
  );
}
