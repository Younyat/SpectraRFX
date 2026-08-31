import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Power, Radio, RotateCcw, ChevronUp, ChevronDown,
  Tag, BookOpen, Navigation, Filter, X,
} from 'lucide-react';
import { useMarkers } from '../../app/store/AppStore';
import { cn } from '../../shared/utils';

// ─── Constants ───────────────────────────────────────────────────────────────

const API_BASE = 'http://localhost:8000/api/live-demodulation';

const MODES = ['AM', 'FM', 'NFM', 'WFM'] as const;
type Mode = typeof MODES[number];

const MODE_COLORS: Record<Mode, string> = {
  AM:  'bg-sky-900/40 border-sky-700/60 text-sky-300',
  FM:  'bg-emerald-900/40 border-emerald-700/60 text-emerald-300',
  NFM: 'bg-violet-900/40 border-violet-700/60 text-violet-300',
  WFM: 'bg-orange-900/40 border-orange-700/60 text-orange-300',
};

const SAMPLE_RATES = [
  { label: '200 kHz', value: 200_000 },
  { label: '250 kHz', value: 250_000 },
  { label: '500 kHz', value: 500_000 },
  { label: '1 MHz',   value: 1_000_000 },
  { label: '2 MHz',   value: 2_000_000 },
  { label: '4 MHz',   value: 4_000_000 },
  { label: '8 MHz',   value: 8_000_000 },
];

const BAND_PRESETS = [
  { label: 'FM broadcast', centerMhz: 98.0,    sampleRate: 2_000_000, mode: 'WFM' as Mode },
  { label: 'PMR446',       centerMhz: 446.094, sampleRate: 250_000,   mode: 'NFM' as Mode },
  { label: 'VHF Air',      centerMhz: 122.5,   sampleRate: 500_000,   mode: 'AM'  as Mode },
  { label: 'UHF Custom',   centerMhz: 433.92,  sampleRate: 500_000,   mode: 'NFM' as Mode },
];

const STORAGE_KEY = 'spectrum-lab:band-labels';

// ─── Types ────────────────────────────────────────────────────────────────────

interface BandLabel {
  id: string;
  name: string;
  createdAt: string;
  centerHz: number;
  mode: Mode;
  sampleRateHz: number;
  gainDb: number;
  volume: number;
  chunkDuration: number;
  bpfEnabled: boolean;
  bpfLowHz: number;
  bpfHighHz: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const formatFreq = (hz: number): string => {
  if (hz >= 1e9) return `${(hz / 1e9).toFixed(6)} GHz`;
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(6)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(3)} kHz`;
  return `${hz.toFixed(0)} Hz`;
};

const loadLabels = (): BandLabel[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as BandLabel[]) : [];
  } catch {
    return [];
  }
};

const saveLabels = (labels: BandLabel[]): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(labels));
  } catch {
    // Storage full or unavailable — silently ignore
  }
};

// ─── Audio engine (Web Audio API) ────────────────────────────────────────────

class AudioEngine {
  private ctx: AudioContext;
  private gainNode: GainNode;
  private analyser: AnalyserNode;
  private nextPlayAt = 0;

  constructor() {
    this.ctx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 48_000 });
    this.gainNode = this.ctx.createGain();
    this.gainNode.gain.value = 0.8;
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.gainNode.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);
    this.nextPlayAt = this.ctx.currentTime;
  }

  resume() { return this.ctx.resume(); }
  setVolume(v: number) { this.gainNode.gain.value = Math.max(0, Math.min(1, v)); }

  playChunk(pcmB64: string, sampleRate: number) {
    try {
      const raw = atob(pcmB64);
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      const samples = new Int16Array(bytes.buffer);
      const floats = new Float32Array(samples.length);
      for (let i = 0; i < samples.length; i++) floats[i] = samples[i] / 32768.0;

      const buf = this.ctx.createBuffer(1, floats.length, sampleRate);
      buf.copyToChannel(floats, 0);
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.gainNode);

      const startAt = Math.max(this.ctx.currentTime + 0.08, this.nextPlayAt);
      src.start(startAt);
      this.nextPlayAt = startAt + buf.duration;
    } catch {
      // ignore decode errors on individual chunks
    }
  }

  getWaveformData(): Float32Array {
    const data = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(data);
    return data;
  }

  getState() { return this.ctx.state; }
  close() { this.ctx.close().catch(() => undefined); }
}

// ─── Waveform canvas ─────────────────────────────────────────────────────────

function WaveformCanvas({ engineRef, isStreaming }: {
  engineRef: React.RefObject<AudioEngine | null>;
  isStreaming: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx2d = canvas.getContext('2d');
    if (!ctx2d) return;

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw);
      const w = canvas.width;
      const h = canvas.height;
      ctx2d.fillStyle = '#0a0a0f';
      ctx2d.fillRect(0, 0, w, h);

      if (!isStreaming || !engineRef.current) {
        ctx2d.strokeStyle = '#78350f';
        ctx2d.lineWidth = 1;
        ctx2d.beginPath();
        ctx2d.moveTo(0, h / 2);
        ctx2d.lineTo(w, h / 2);
        ctx2d.stroke();
        return;
      }

      const data = engineRef.current.getWaveformData();
      const step = Math.ceil(data.length / w);

      ctx2d.strokeStyle = '#1c1917';
      ctx2d.lineWidth = 1;
      for (let i = 1; i < 4; i++) {
        const y = (h / 4) * i;
        ctx2d.beginPath(); ctx2d.moveTo(0, y); ctx2d.lineTo(w, y); ctx2d.stroke();
      }

      ctx2d.strokeStyle = '#f59e0b';
      ctx2d.lineWidth = 1.5;
      ctx2d.shadowColor = '#f59e0b';
      ctx2d.shadowBlur = 4;
      ctx2d.beginPath();
      for (let x = 0; x < w; x++) {
        const idx = x * step;
        let max = 0;
        for (let j = 0; j < step && idx + j < data.length; j++) {
          if (Math.abs(data[idx + j]) > Math.abs(max)) max = data[idx + j];
        }
        const y = ((1 - max) / 2) * h;
        x === 0 ? ctx2d.moveTo(x, y) : ctx2d.lineTo(x, y);
      }
      ctx2d.stroke();
      ctx2d.shadowBlur = 0;
    };

    draw();
    return () => cancelAnimationFrame(rafRef.current);
  }, [isStreaming, engineRef]);

  return (
    <canvas
      ref={canvasRef}
      width={560}
      height={80}
      className="w-full rounded"
      style={{ background: '#0a0a0f' }}
    />
  );
}

// ─── S-Meter ─────────────────────────────────────────────────────────────────

function SMeter({ rmsDb }: { rmsDb: number }) {
  const pct = Math.max(0, Math.min(100, ((rmsDb + 60) / 60) * 100));
  const color = pct > 80 ? '#ef4444' : pct > 60 ? '#f59e0b' : '#22c55e';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-amber-600 font-mono">
        <span>S1</span><span>S3</span><span>S5</span><span>S7</span><span>S9</span><span>+20</span><span>+40</span>
      </div>
      <div className="h-3 rounded bg-stone-900 border border-stone-700 overflow-hidden">
        <div
          className="h-full rounded transition-all duration-75"
          style={{ width: `${pct}%`, background: `linear-gradient(to right, #22c55e, ${color})` }}
        />
      </div>
    </div>
  );
}

// ─── Frequency display ────────────────────────────────────────────────────────

function FreqDisplay({ hz, onStep }: { hz: number; onStep: (delta: number) => void }) {
  const mhz = hz / 1_000_000;
  const parts = mhz.toFixed(6).split('.');
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex-1 font-mono text-3xl tracking-widest text-amber-400 bg-stone-950 border border-amber-900/50 rounded px-4 py-3 text-center select-none"
        style={{ textShadow: '0 0 12px #f59e0b88', letterSpacing: '0.15em' }}
      >
        {parts[0]}
        <span className="text-amber-600">.</span>
        {parts[1]}
        <span className="text-amber-700 text-lg ml-2">MHz</span>
      </div>
      <div className="flex flex-col gap-1">
        <button onClick={() => onStep(100_000)} className="w-8 h-8 rounded bg-stone-800 hover:bg-amber-900 border border-stone-600 flex items-center justify-center">
          <ChevronUp className="w-4 h-4 text-amber-400" />
        </button>
        <button onClick={() => onStep(-100_000)} className="w-8 h-8 rounded bg-stone-800 hover:bg-amber-900 border border-stone-600 flex items-center justify-center">
          <ChevronDown className="w-4 h-4 text-amber-400" />
        </button>
      </div>
    </div>
  );
}

// ─── BPF Visualizer ───────────────────────────────────────────────────────────

function BpfVisualizer({ centerHz, lowHz, highHz, sampleRate }: {
  centerHz: number;
  lowHz: number;
  highHz: number;
  sampleRate: number;
}) {
  const halfBw = sampleRate / 2;
  const lowPct  = Math.max(0, Math.min(100, ((lowHz  + halfBw) / (2 * halfBw)) * 100));
  const highPct = Math.max(0, Math.min(100, ((highHz + halfBw) / (2 * halfBw)) * 100));

  return (
    <div className="space-y-1">
      <div className="relative h-8 rounded bg-stone-900 border border-stone-800 overflow-hidden select-none">
        {/* Rejected bands */}
        <div className="absolute inset-y-0 left-0 bg-red-950/20" style={{ width: `${lowPct}%` }} />
        <div className="absolute inset-y-0 right-0 bg-red-950/20" style={{ width: `${100 - highPct}%` }} />
        {/* Passband */}
        <div
          className="absolute inset-y-1 rounded bg-cyan-500/15 border border-cyan-700/30"
          style={{ left: `${lowPct}%`, right: `${100 - highPct}%` }}
        />
        {/* Carrier marker */}
        <div className="absolute top-0 bottom-0 left-1/2 w-px bg-amber-700/40" />
        {/* Band-edge markers */}
        <div className="absolute top-0 bottom-0 w-px bg-cyan-600/60" style={{ left: `${lowPct}%` }} />
        <div className="absolute top-0 bottom-0 w-px bg-cyan-600/60" style={{ left: `${highPct}%` }} />
        {/* Axis labels */}
        <span className="absolute bottom-0.5 left-1 text-[8px] text-stone-600 font-mono">
          -{(halfBw / 1000).toFixed(0)}k
        </span>
        <span className="absolute bottom-0.5 right-1 text-[8px] text-stone-600 font-mono">
          +{(halfBw / 1000).toFixed(0)}k
        </span>
        <span className="absolute top-0.5 left-1/2 -translate-x-1/2 text-[8px] text-amber-600/70 font-mono">
          0
        </span>
      </div>
      {/* Absolute frequency edges */}
      <div className="flex justify-between text-[10px] text-stone-600 font-mono">
        <span className="text-cyan-700">{formatFreq(centerHz + lowHz)}</span>
        <span className="text-stone-500">
          BW: <span className="text-cyan-400">{((highHz - lowHz) / 1000).toFixed(1)} kHz</span>
        </span>
        <span className="text-cyan-700">{formatFreq(centerHz + highHz)}</span>
      </div>
    </div>
  );
}

// ─── Band Label Card ──────────────────────────────────────────────────────────

function BandLabelCard({
  label,
  onTune,
  onDelete,
}: {
  label: BandLabel;
  onTune: () => void;
  onDelete: () => void;
}) {
  const date = new Date(label.createdAt);
  const dateStr = `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

  return (
    <div className="rounded border border-stone-700/40 bg-stone-950 p-3 hover:border-stone-600/60 transition-colors">
      <div className="flex items-start justify-between gap-2">
        {/* Info */}
        <div className="min-w-0 space-y-1">
          <div className="text-sm font-bold text-stone-100 truncate">{label.name}</div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-mono text-amber-400 tracking-wide">
              {(label.centerHz / 1e6).toFixed(6)} MHz
            </span>
            <span className={cn(
              'text-[10px] font-bold px-1.5 py-0.5 rounded border',
              MODE_COLORS[label.mode]
            )}>
              {label.mode}
            </span>
            <span className="text-[10px] text-stone-500 font-mono">
              {(label.sampleRateHz / 1e6).toFixed(2)} MS/s
            </span>
            {label.bpfEnabled && (
              <span className="text-[10px] text-cyan-400 border border-cyan-900/50 rounded px-1.5 bg-cyan-950/30">
                BPF {((label.bpfHighHz - label.bpfLowHz) / 1000).toFixed(0)} kHz
              </span>
            )}
          </div>
          <div className="text-[10px] text-stone-600 font-mono">
            Gain: {label.gainDb} dB &nbsp;·&nbsp;
            Vol: {Math.round(label.volume * 100)} % &nbsp;·&nbsp;
            {label.chunkDuration} s &nbsp;·&nbsp;
            {dateStr}
          </div>
        </div>
        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onTune}
            className="h-7 px-2 rounded bg-amber-900/20 border border-amber-800/50 text-amber-400 text-[11px] font-bold hover:bg-amber-900/40 hover:border-amber-700 transition-all flex items-center gap-1"
            title="Load settings from this label"
          >
            <Navigation className="w-3 h-3" />
            TUNE
          </button>
          <button
            onClick={onDelete}
            className="w-7 h-7 rounded border border-stone-700 text-stone-500 text-sm hover:bg-red-950/30 hover:border-red-800 hover:text-red-400 flex items-center justify-center transition-all"
            title="Delete label"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main View ───────────────────────────────────────────────────────────────

export const LiveDemodulationView: React.FC = () => {
  const markers = useMarkers();

  const markerCenter = (() => {
    if (markers.length >= 2) {
      const [a, b] = markers;
      return (a.frequency + b.frequency) / 2;
    }
    return null;
  })();

  // ── Core receiver state ────────────────────────────────────────────────
  const [centerHz, setCenterHz] = useState(markerCenter ?? 98_000_000);
  const [centerInput, setCenterInput] = useState(((markerCenter ?? 98_000_000) / 1e6).toFixed(6));
  const [mode, setMode] = useState<Mode>('WFM');
  const [sampleRate, setSampleRate] = useState(2_000_000);
  const [gainDb, setGainDb] = useState(30);
  const [volume, setVolume] = useState(0.8);
  const [chunkDuration, setChunkDuration] = useState(0.5);

  const [isStreaming, setIsStreaming] = useState(false);
  const [status, setStatus] = useState<string>('idle');
  const [rmsDb, setRmsDb] = useState(-60);
  const [chunksReceived, setChunksReceived] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState('Offline');

  // ── Band Pass Filter state ─────────────────────────────────────────────
  const [bpfEnabled, setBpfEnabled] = useState(false);
  const [bpfLowHz, setBpfLowHz] = useState(-100_000);
  const [bpfHighHz, setBpfHighHz] = useState(100_000);

  // ── Band Repository state ──────────────────────────────────────────────
  const [bandLabels, setBandLabels] = useState<BandLabel[]>(loadLabels);
  const [repoExpanded, setRepoExpanded] = useState(false);
  const [labelDialogOpen, setLabelDialogOpen] = useState(false);
  const [labelName, setLabelName] = useState('');

  // ── Refs ───────────────────────────────────────────────────────────────
  const audioRef = useRef<AudioEngine | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // ── Persist band labels ────────────────────────────────────────────────
  useEffect(() => {
    saveLabels(bandLabels);
  }, [bandLabels]);

  // ── Sync volume to engine ──────────────────────────────────────────────
  useEffect(() => {
    audioRef.current?.setVolume(volume);
  }, [volume]);

  // ── Sync marker center freq (only when idle) ───────────────────────────
  useEffect(() => {
    if (markerCenter && !isStreaming) {
      setCenterHz(markerCenter);
      setCenterInput((markerCenter / 1e6).toFixed(6));
    }
  }, [markerCenter, isStreaming]);

  // ── Cleanup on unmount ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      esRef.current?.close();
      audioRef.current?.close();
      fetch(`${API_BASE}/stop`, { method: 'POST' }).catch(() => undefined);
    };
  }, []);

  // ── Freq step ──────────────────────────────────────────────────────────
  const stepFreq = useCallback((delta: number) => {
    setCenterHz((prev) => {
      const next = Math.max(100_000, prev + delta);
      setCenterInput((next / 1e6).toFixed(6));
      if (isStreaming) {
        fetch(`${API_BASE}/update`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ center_hz: next }),
        }).catch(() => undefined);
      }
      return next;
    });
  }, [isStreaming]);

  const applyFreqInput = () => {
    const v = parseFloat(centerInput);
    if (!Number.isFinite(v) || v <= 0) return;
    const hz = Math.round(v * 1e6);
    setCenterHz(hz);
    if (isStreaming) {
      fetch(`${API_BASE}/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ center_hz: hz }),
      }).catch(() => undefined);
    }
  };

  // ── Gain change ────────────────────────────────────────────────────────
  const applyGain = (g: number) => {
    setGainDb(g);
    if (isStreaming) {
      fetch(`${API_BASE}/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gain_db: g }),
      }).catch(() => undefined);
    }
  };

  // ── BPF change ─────────────────────────────────────────────────────────
  const applyBpf = useCallback((
    enabled: boolean,
    low: number,
    high: number,
  ) => {
    setBpfEnabled(enabled);
    setBpfLowHz(low);
    setBpfHighHz(high);
    if (isStreaming) {
      fetch(`${API_BASE}/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bpf_update: true,
          bpf_low_hz:  enabled ? low  : null,
          bpf_high_hz: enabled ? high : null,
        }),
      }).catch(() => undefined);
    }
  }, [isStreaming]);

  // ── Stop (shared by handleStop button and tuneToLabel) ────────────────
  const stopReceiver = useCallback(async () => {
    esRef.current?.close();
    esRef.current = null;
    setIsStreaming(false);
    setStatus('idle');
    setStatusMsg('Offline');
    await fetch(`${API_BASE}/stop`, { method: 'POST' }).catch(() => undefined);
  }, []);

  // ── Band label actions ─────────────────────────────────────────────────
  const saveBandLabel = (name: string) => {
    const trimmed = name.trim() || `Band @ ${(centerHz / 1e6).toFixed(3)} MHz`;
    const label: BandLabel = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: trimmed,
      createdAt: new Date().toISOString(),
      centerHz,
      mode,
      sampleRateHz: sampleRate,
      gainDb,
      volume,
      chunkDuration,
      bpfEnabled,
      bpfLowHz,
      bpfHighHz,
    };
    setBandLabels((prev) => [label, ...prev]);
    setLabelDialogOpen(false);
    setLabelName('');
    setRepoExpanded(true);
  };

  const deleteBandLabel = (id: string) => {
    setBandLabels((prev) => prev.filter((l) => l.id !== id));
  };

  const tuneToLabel = async (label: BandLabel) => {
    if (isStreaming) await stopReceiver();
    setCenterHz(label.centerHz);
    setCenterInput((label.centerHz / 1e6).toFixed(6));
    setMode(label.mode);
    setSampleRate(label.sampleRateHz);
    setGainDb(label.gainDb);
    setVolume(label.volume);
    setChunkDuration(label.chunkDuration);
    setBpfEnabled(label.bpfEnabled);
    setBpfLowHz(label.bpfLowHz);
    setBpfHighHz(label.bpfHighHz);
  };

  // ── Start ──────────────────────────────────────────────────────────────
  const handleStart = async () => {
    setError(null);
    setChunksReceived(0);
    setRmsDb(-60);

    if (!audioRef.current) audioRef.current = new AudioEngine();
    await audioRef.current.resume();

    try {
      const resp = await fetch(`${API_BASE}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          center_hz:      centerHz,
          mode:           mode.toLowerCase(),
          sample_rate_hz: sampleRate,
          gain_db:        gainDb,
          chunk_duration: chunkDuration,
          bpf_low_hz:     bpfEnabled ? bpfLowHz  : null,
          bpf_high_hz:    bpfEnabled ? bpfHighHz : null,
        }),
      });
      if (!resp.ok) {
        const detail = (await resp.json().catch(() => ({}))).detail ?? 'Start failed';
        throw new Error(String(detail));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }

    setIsStreaming(true);
    setStatus('starting');
    setStatusMsg('Connecting…');

    const es = new EventSource(`${API_BASE}/stream`);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'connected') {
          setStatusMsg('Tuning…');
        } else if (msg.type === 'status' && msg.message === 'streaming') {
          setStatus('streaming');
          setStatusMsg('ON AIR');
        } else if (msg.type === 'audio_chunk') {
          audioRef.current?.playChunk(msg.pcm_b64, msg.sample_rate);
          setRmsDb(typeof msg.rms_db === 'number' ? msg.rms_db : -60);
          setChunksReceived((n) => n + 1);
          setStatusMsg('ON AIR');
        } else if (msg.type === 'heartbeat') {
          setStatusMsg('Waiting for signal…');
        } else if (msg.type === 'error') {
          setError(String(msg.message ?? 'Worker error'));
          setStatusMsg('Error');
        } else if (msg.type === 'stream_end') {
          setIsStreaming(false);
          setStatusMsg('Offline');
          es.close();
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      if (isStreaming) setStatusMsg('Stream lost');
    };
  };

  // ── Stop ───────────────────────────────────────────────────────────────
  const handleStop = stopReceiver;

  // ── Band preset ────────────────────────────────────────────────────────
  const applyPreset = (preset: typeof BAND_PRESETS[0]) => {
    const hz = Math.round(preset.centerMhz * 1e6);
    setCenterHz(hz);
    setCenterInput(preset.centerMhz.toFixed(6));
    setSampleRate(preset.sampleRate);
    setMode(preset.mode);
  };

  // ── Derived ────────────────────────────────────────────────────────────
  const onAir = isStreaming && status === 'streaming';
  const bpfBwKhz = ((bpfHighHz - bpfLowHz) / 1000).toFixed(1);

  // ── BPF input helpers ──────────────────────────────────────────────────
  const handleBpfLow = (val: string) => {
    const v = parseFloat(val) * 1000;
    if (!Number.isFinite(v) || v >= 0) return;
    applyBpf(true, v, bpfHighHz);
  };
  const handleBpfHigh = (val: string) => {
    const v = parseFloat(val) * 1000;
    if (!Number.isFinite(v) || v <= 0) return;
    applyBpf(true, bpfLowHz, v);
  };

  // ── UI ─────────────────────────────────────────────────────────────────
  return (
    <div className="h-full overflow-auto bg-stone-950 text-stone-100" style={{ fontFamily: 'monospace' }}>
      <div className="max-w-3xl mx-auto p-5 space-y-4">

        {/* ── Header ── */}
        <div className="flex items-center justify-between border-b border-amber-900/40 pb-3">
          <div className="flex items-center gap-3">
            <Radio className="w-6 h-6 text-amber-400" />
            <div>
              <h1 className="text-base font-bold tracking-widest uppercase text-amber-300">Live Demodulation</h1>
              <p className="text-xs text-stone-500">Real-time AM · FM · NFM · WFM audio receiver</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className={cn(
              'w-3 h-3 rounded-full border',
              onAir ? 'bg-red-500 border-red-300 shadow-[0_0_8px_#ef4444]' : 'bg-stone-700 border-stone-600'
            )} />
            <span className={cn('text-xs font-bold tracking-widest uppercase',
              onAir ? 'text-red-400' : 'text-stone-500'
            )}>
              {statusMsg}
            </span>
          </div>
        </div>

        {/* ── Radio body ── */}
        <div
          className="rounded-xl border border-amber-900/30 bg-stone-900 p-5 space-y-5"
          style={{ boxShadow: onAir ? '0 0 24px #f59e0b18' : undefined }}
        >
          {/* Frequency */}
          <div className="space-y-2">
            <label className="text-xs text-stone-500 uppercase tracking-wider">Frequency</label>
            <FreqDisplay hz={centerHz} onStep={stepFreq} />
            <div className="flex gap-2 items-center">
              <input
                value={centerInput}
                onChange={(e) => setCenterInput(e.target.value)}
                onBlur={applyFreqInput}
                onKeyDown={(e) => e.key === 'Enter' && applyFreqInput()}
                placeholder="MHz"
                className="flex-1 h-8 rounded border border-stone-700 bg-stone-950 px-3 text-sm text-amber-300 font-mono outline-none focus:border-amber-600"
              />
              <button
                onClick={applyFreqInput}
                className="h-8 px-3 rounded bg-stone-800 hover:bg-stone-700 text-xs text-stone-300 border border-stone-600"
              >
                Set
              </button>
              {markerCenter && (
                <button
                  onClick={() => { setCenterHz(markerCenter); setCenterInput((markerCenter / 1e6).toFixed(6)); }}
                  className="h-8 px-3 rounded bg-stone-800 hover:bg-amber-900/40 text-xs text-amber-400 border border-amber-900/40"
                >
                  <RotateCcw className="w-3 h-3 inline mr-1" />
                  From markers
                </button>
              )}
            </div>
          </div>

          {/* Modulation */}
          <div className="space-y-2">
            <label className="text-xs text-stone-500 uppercase tracking-wider">Modulation</label>
            <div className="flex gap-2">
              {MODES.map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  disabled={isStreaming}
                  className={cn(
                    'flex-1 h-10 rounded font-bold text-sm tracking-widest border transition-all',
                    mode === m
                      ? 'bg-amber-500/20 border-amber-500 text-amber-300 shadow-[0_0_8px_#f59e0b44]'
                      : 'bg-stone-950 border-stone-700 text-stone-400 hover:border-stone-500',
                    isStreaming && mode !== m && 'opacity-40 cursor-not-allowed',
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* Waveform */}
          <div className="space-y-1">
            <label className="text-xs text-stone-500 uppercase tracking-wider">Audio waveform</label>
            <WaveformCanvas engineRef={audioRef} isStreaming={onAir} />
          </div>

          {/* S-Meter */}
          <div className="space-y-1">
            <label className="text-xs text-stone-500 uppercase tracking-wider">Signal level</label>
            <SMeter rmsDb={rmsDb} />
            <div className="text-right text-[10px] text-stone-600 font-mono">{rmsDb.toFixed(1)} dBFS</div>
          </div>

          {/* Controls grid */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs text-stone-500 uppercase tracking-wider">RF gain — {gainDb} dB</label>
              <input
                type="range" min={0} max={76} step={1} value={gainDb}
                onChange={(e) => applyGain(Number(e.target.value))}
                className="w-full accent-amber-500"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500 uppercase tracking-wider">Volume — {Math.round(volume * 100)}%</label>
              <input
                type="range" min={0} max={1} step={0.01} value={volume}
                onChange={(e) => setVolume(Number(e.target.value))}
                className="w-full accent-amber-500"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500 uppercase tracking-wider">Sample rate</label>
              <select
                value={sampleRate}
                onChange={(e) => setSampleRate(Number(e.target.value))}
                disabled={isStreaming}
                className="w-full h-8 rounded border border-stone-700 bg-stone-950 px-2 text-sm text-stone-200 outline-none focus:border-amber-600 disabled:opacity-50"
              >
                {SAMPLE_RATES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500 uppercase tracking-wider">Chunk / latency</label>
              <select
                value={chunkDuration}
                onChange={(e) => setChunkDuration(Number(e.target.value))}
                disabled={isStreaming}
                className="w-full h-8 rounded border border-stone-700 bg-stone-950 px-2 text-sm text-stone-200 outline-none focus:border-amber-600 disabled:opacity-50"
              >
                <option value={0.25}>0.25 s — low latency</option>
                <option value={0.5}>0.5 s — balanced</option>
                <option value={1.0}>1.0 s — smooth</option>
                <option value={2.0}>2.0 s — hi-quality</option>
              </select>
            </div>
          </div>

          {/* ── Band Pass Filter ── */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs text-stone-500 uppercase tracking-wider flex items-center gap-1.5">
                <Filter className="w-3 h-3" />
                Band Pass Filter
              </label>
              <button
                onClick={() => applyBpf(!bpfEnabled, bpfLowHz, bpfHighHz)}
                className={cn(
                  'flex items-center gap-1.5 h-6 px-2.5 rounded text-[11px] font-bold border transition-all',
                  bpfEnabled
                    ? 'bg-cyan-900/30 border-cyan-700/60 text-cyan-300 shadow-[0_0_6px_#06b6d422]'
                    : 'bg-stone-900 border-stone-600 text-stone-400 hover:border-stone-500',
                )}
              >
                <div className={cn(
                  'w-1.5 h-1.5 rounded-full',
                  bpfEnabled ? 'bg-cyan-400 shadow-[0_0_4px_#22d3ee]' : 'bg-stone-600'
                )} />
                {bpfEnabled ? 'ON' : 'OFF'}
              </button>
            </div>

            {bpfEnabled && (
              <div className="rounded border border-cyan-900/30 bg-stone-950/60 p-3 space-y-3">
                <BpfVisualizer
                  centerHz={centerHz}
                  lowHz={bpfLowHz}
                  highHz={bpfHighHz}
                  sampleRate={sampleRate}
                />
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-[10px] text-stone-500 uppercase tracking-wider">Low cut offset (kHz)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={(bpfLowHz / 1000).toFixed(1)}
                      onChange={(e) => handleBpfLow(e.target.value)}
                      className="w-full h-7 rounded border border-stone-700 bg-stone-900 px-2 text-xs text-cyan-300 font-mono outline-none focus:border-cyan-700"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] text-stone-500 uppercase tracking-wider">High cut offset (kHz)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={(bpfHighHz / 1000).toFixed(1)}
                      onChange={(e) => handleBpfHigh(e.target.value)}
                      className="w-full h-7 rounded border border-stone-700 bg-stone-900 px-2 text-xs text-cyan-300 font-mono outline-none focus:border-cyan-700"
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between text-[10px] font-mono text-stone-600">
                  <span>
                    Passband: <span className="text-cyan-500">{bpfBwKhz} kHz</span>
                  </span>
                  <span>
                    {bpfEnabled && isStreaming && (
                      <span className="text-cyan-700 uppercase tracking-wide">Active</span>
                    )}
                  </span>
                  <span>
                    Centre offset: <span className="text-stone-400">
                      {((bpfLowHz + bpfHighHz) / 2000).toFixed(1)} kHz
                    </span>
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Band presets */}
          <div className="space-y-2">
            <label className="text-xs text-stone-500 uppercase tracking-wider">Quick presets</label>
            <div className="flex flex-wrap gap-2">
              {BAND_PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => applyPreset(p)}
                  disabled={isStreaming}
                  className="h-7 px-3 rounded border border-stone-700 bg-stone-950 hover:border-amber-700 hover:text-amber-300 text-xs text-stone-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* ── Label Band ── */}
          {!labelDialogOpen ? (
            <button
              onClick={() => { setLabelName(''); setLabelDialogOpen(true); }}
              className="w-full h-8 rounded border border-dashed border-stone-700 hover:border-amber-800/60 text-xs text-stone-500 hover:text-amber-400 flex items-center justify-center gap-2 transition-colors"
            >
              <Tag className="w-3.5 h-3.5" />
              Label This Band
            </button>
          ) : (
            <div className="rounded border border-amber-800/40 bg-stone-950 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-amber-400 font-bold uppercase tracking-wider">Label Band</span>
                <span className="text-[10px] text-stone-500 font-mono">
                  {(centerHz / 1e6).toFixed(6)} MHz · {mode}
                  {bpfEnabled ? ` · BPF ${bpfBwKhz} kHz` : ''}
                </span>
              </div>
              <input
                autoFocus
                value={labelName}
                onChange={(e) => setLabelName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveBandLabel(labelName);
                  if (e.key === 'Escape') setLabelDialogOpen(false);
                }}
                placeholder="e.g. Radio Clásica 98 MHz"
                className="w-full h-8 rounded border border-stone-700 bg-stone-900 px-3 text-sm text-stone-200 placeholder-stone-600 outline-none focus:border-amber-700"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => saveBandLabel(labelName)}
                  className="flex-1 h-7 rounded bg-amber-900/30 border border-amber-700/60 text-amber-300 text-xs font-bold hover:bg-amber-900/50 transition-colors"
                >
                  Save Label
                </button>
                <button
                  onClick={() => setLabelDialogOpen(false)}
                  className="h-7 px-3 rounded bg-stone-800 border border-stone-700 text-stone-400 text-xs hover:bg-stone-700 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">
              {error}
            </div>
          )}

          {/* Start / Stop button */}
          <button
            onClick={isStreaming ? handleStop : handleStart}
            className={cn(
              'w-full h-14 rounded-lg font-bold text-base tracking-widest uppercase border-2 flex items-center justify-center gap-3 transition-all',
              isStreaming
                ? 'bg-red-900/30 border-red-600 text-red-300 hover:bg-red-900/50 shadow-[0_0_16px_#dc262644]'
                : 'bg-amber-900/20 border-amber-600 text-amber-300 hover:bg-amber-900/40 shadow-[0_0_16px_#f59e0b22]'
            )}
          >
            <Power className="w-5 h-5" />
            {isStreaming ? 'Stop Receiver' : 'Start Receiver'}
          </button>
        </div>

        {/* Stats footer */}
        <div className="grid grid-cols-4 gap-2 text-center">
          {[
            { label: 'Center',      value: formatFreq(centerHz) },
            { label: 'Mode',        value: mode },
            { label: 'Sample rate', value: `${(sampleRate / 1e6).toFixed(2)} MS/s` },
            { label: 'Chunks',      value: String(chunksReceived) },
          ].map((s) => (
            <div key={s.label} className="rounded border border-stone-800 bg-stone-900 p-2">
              <div className="text-[10px] uppercase text-stone-600">{s.label}</div>
              <div className="text-xs font-mono text-stone-300 mt-0.5 truncate">{s.value}</div>
            </div>
          ))}
        </div>

        {/* ── Band Repository ── */}
        <div className="rounded-xl border border-stone-700/40 bg-stone-900/40 overflow-hidden">
          {/* Collapsible header */}
          <button
            onClick={() => setRepoExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-stone-800/40 transition-colors"
          >
            <div className="flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-stone-500" />
              <span className="text-xs font-bold uppercase tracking-widest text-stone-400">
                Band Repository
              </span>
              {bandLabels.length > 0 && (
                <span className="text-[10px] bg-amber-900/30 text-amber-500 border border-amber-800/40 rounded px-1.5 py-0.5 font-mono">
                  {bandLabels.length}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {bandLabels.length === 0 && !repoExpanded && (
                <span className="text-[10px] text-stone-600">No saved bands — use &quot;Label This Band&quot; above</span>
              )}
              {repoExpanded
                ? <ChevronUp className="w-3.5 h-3.5 text-stone-500" />
                : <ChevronDown className="w-3.5 h-3.5 text-stone-500" />}
            </div>
          </button>

          {/* Expanded list */}
          {repoExpanded && (
            <div className="border-t border-stone-800/60 p-3 space-y-2 max-h-96 overflow-y-auto">
              {bandLabels.length === 0 ? (
                <div className="text-center py-8 space-y-2">
                  <BookOpen className="w-8 h-8 mx-auto text-stone-700" />
                  <div className="text-xs text-stone-600">No bands saved yet</div>
                  <div className="text-[10px] text-stone-700">
                    Configure your receiver and click &quot;Label This Band&quot; to save
                  </div>
                </div>
              ) : (
                bandLabels.map((label) => (
                  <BandLabelCard
                    key={label.id}
                    label={label}
                    onTune={() => tuneToLabel(label)}
                    onDelete={() => deleteBandLabel(label.id)}
                  />
                ))
              )}
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
