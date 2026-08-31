import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BleRffiStudioApiService, StudioJob, StudioLiveCheckResult, StudioLiveSelectableBundle, StudioPrepareAndTrainSummary,
} from '../../../app/services/bleRffiStudioApi';

const api = new BleRffiStudioApiService();
const JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled']);

// Same BLE band spectrum_stream_worker.py itself gates burst detection on
// (see _within_ble_band there) -- kept in sync manually since these are two
// different runtimes (Python worker vs this React component), both reading
// the same well-known, effectively-frozen ISM-band constants.
const BLE_BAND_START_HZ = 2_400_000_000;
const BLE_BAND_STOP_HZ = 2_483_500_000;

function isWithinBleBand(centerFrequencyHz: number, sampleRateHz: number): boolean {
  const tunedStart = centerFrequencyHz - sampleRateHz / 2;
  const tunedStop = centerFrequencyHz + sampleRateHz / 2;
  return tunedStart <= BLE_BAND_STOP_HZ && tunedStop >= BLE_BAND_START_HZ;
}

// Short, operator-facing names for the model_type strings training_service.py
// produces -- shown as a compact badge next to the task, per the operator's
// explicit request to know AT A GLANCE which model type (CNN1D, Random
// Forest, etc.) is behind each entry.
const MODEL_TYPE_LABELS: Record<string, string> = {
  logistic_regression: 'Reg. Logistica',
  svm_rbf: 'SVM',
  random_forest: 'Random Forest',
  cnn1d: 'CNN1D',
  cnn2d: 'CNN2D',
};

interface Props {
  centerFrequencyHz: number;
  sampleRateHz: number;
}

// One entry per physical device that actually has a working, approved
// model -- a device with no approved model never appears at all (the
// backend already excludes anything not APPROVED_FOR_LIVE_PILOT or whose
// reference capture no longer resolves, see list_live_selectable_bundles()).
function groupByDevice(bundles: StudioLiveSelectableBundle[]): Record<string, StudioLiveSelectableBundle[]> {
  const groups: Record<string, StudioLiveSelectableBundle[]> = {};
  for (const bundle of bundles) {
    const device = bundle.physical_units.length ? bundle.physical_units.join(' + ') : 'General';
    (groups[device] ||= []).push(bundle);
  }
  return groups;
}

const DEFAULT_HOLD_SECONDS = 6;
const GREEN_CONFIDENCE_THRESHOLD = 0.70;

// Color reflects the ACTUAL confidence, not just a binary
// identified/not-identified flag -- red when nothing real was identified
// (never green just because a burst happened to score above the model's
// calibrated acceptance_threshold), a red-to-green gradient tied to how far
// above that threshold the confidence sits once something IS identified,
// and full green only from 70% up, exactly as requested. Returns a hue
// (0=red .. 120=green) rather than a finished color string, so callers can
// compose it into modern `hsl(H S% L% / A)` strings at whatever alpha they
// need for borders vs. fills vs. solid dots.
function resultHue(result: StudioLiveCheckResult | null): number {
  if (!result || result.error || result.final_decision !== 'IDENTIFIED') return 0;
  const probability = result.class_probability ?? 0;
  if (probability >= GREEN_CONFIDENCE_THRESHOLD) return 120;
  const lowerBound = result.acceptance_threshold ?? 0.5;
  const t = Math.max(0, Math.min(1, (probability - lowerBound) / Math.max(0.0001, GREEN_CONFIDENCE_THRESHOLD - lowerBound)));
  return Math.round(t * 120);
}
const hsl = (hue: number, alpha = 1) => `hsl(${hue} 70% 50% / ${alpha})`;

// "Comprobacion de deteccion real": an automated version of the exact manual
// baseline-vs-device-on comparison used to diagnose that AUTO-random_forest
// -a13395082d-bundle doesn't really discriminate its target from background
// (its confidence hovered 0.52-0.82 whether or not the device was on, and it
// never once predicted BACKGROUND_ENVIRONMENT). Rather than the operator
// running that comparison by hand every time, this collects the same two
// phases automatically and applies the same judgement call: does confidence
// AND identification rate rise meaningfully once the device is really on?
type HealthCheckPhase = 'idle' | 'instructions_baseline' | 'baseline' | 'instructions_active' | 'active' | 'done';
const HEALTH_CHECK_PHASE_SECONDS = 15;
const HEALTH_CHECK_MIN_RATE_DELTA = 0.3;
const HEALTH_CHECK_MIN_MEAN_DELTA = 0.15;

interface HealthCheckVerdict {
  passed: boolean;
  baselineRate: number;
  activeRate: number;
  baselineMean: number;
  activeMean: number;
  baselineCount: number;
  activeCount: number;
  ranAt: string;
}

function summarizeSamples(samples: StudioLiveCheckResult[]): { rate: number; mean: number } {
  if (!samples.length) return { rate: 0, mean: 0 };
  const identified = samples.filter((s) => s.final_decision === 'IDENTIFIED' && !s.error);
  const withProbability = samples.filter((s) => s.class_probability != null);
  const mean = withProbability.length ? withProbability.reduce((sum, s) => sum + (s.class_probability || 0), 0) / withProbability.length : 0;
  return { rate: identified.length / samples.length, mean };
}

function computeVerdict(baseline: StudioLiveCheckResult[], active: StudioLiveCheckResult[]): HealthCheckVerdict {
  const b = summarizeSamples(baseline);
  const a = summarizeSamples(active);
  const passed = (a.rate - b.rate) >= HEALTH_CHECK_MIN_RATE_DELTA || (a.mean - b.mean) >= HEALTH_CHECK_MIN_MEAN_DELTA;
  return {
    passed, baselineRate: b.rate, activeRate: a.rate, baselineMean: b.mean, activeMean: a.mean,
    baselineCount: baseline.length, activeCount: active.length, ranAt: new Date().toISOString(),
  };
}

function loadStoredVerdict(bundleId: string): HealthCheckVerdict | null {
  try {
    const raw = window.localStorage.getItem(`ble-rffi-health-check-${bundleId}`);
    return raw ? (JSON.parse(raw) as HealthCheckVerdict) : null;
  } catch {
    return null;
  }
}

function storeVerdict(bundleId: string, verdict: HealthCheckVerdict): void {
  try {
    window.localStorage.setItem(`ble-rffi-health-check-${bundleId}`, JSON.stringify(verdict));
  } catch {
    // Best-effort only -- losing the persisted verdict is not worth failing over.
  }
}

// Styled after SpectrumToolsPanel.tsx (same button + dropdown + active-badge
// pattern) so this reads as part of the same "Spectrum Tools" family, per the
// operator's explicit request -- but deliberately a separate, additive
// component: it never touches spectrumTools state, never renders inside
// SpectrumToolsPanel itself, and is positioned as a sibling overlay so a bug
// here cannot affect the existing tools panel.
export function BleRffiLiveModelPanel({ centerFrequencyHz, sampleRateHz }: Props) {
  const [open, setOpen] = useState(false);
  const [bundles, setBundles] = useState<StudioLiveSelectableBundle[]>([]);
  const [activeBundleId, setActiveBundleId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [deletingBundleId, setDeletingBundleId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // A positive detection is easy to miss: the live burst rate varies a lot,
  // and a poll that lands right after a detection can show "esperando..."
  // again a second later even though something WAS just identified. Holding
  // the last positive result on screen for a few seconds (operator-adjustable,
  // since how long is "long enough" depends on how fast the operator can look
  // over) makes a real detection actually visible instead of flashing by.
  const [holdSeconds, setHoldSeconds] = useState(DEFAULT_HOLD_SECONDS);
  const [displayedResult, setDisplayedResult] = useState<StudioLiveCheckResult | null>(null);
  const heldAtRef = useRef(0);

  // "Vigilar varios dispositivos a la vez": independent of activeBundleId
  // (the single-select health-check flow below) -- several already-good
  // per-device detectors run side by side, sharing the SAME decoded live
  // burst (see real_spectrum_stream.py's _live_check_worker_loop -- decode
  // once, classify once per watched bundle, never a per-model capture), so
  // the operator sees WHICH device, if any, is on right now, instead of a
  // single multi-class model that can only ever guess one of N known
  // devices (real limitation found and documented in backend/README.md's
  // device-scrubbing section: that task's own split never includes an
  // "absent" class at all).
  //
  // Selection is per-DEVICE, not per-bundle: one row per device (real
  // request -- a device with 5 trained model_type variants must not turn
  // into 5 separate rows to tick). watchModelChoice remembers which single
  // model_type is used for each watched device, defaulting to whichever has
  // the lowest measured false-positive rate (see bundle.reliability).
  const [watchDevices, setWatchDevices] = useState<Set<string>>(new Set());
  const [watchModelChoice, setWatchModelChoice] = useState<Record<string, string>>({});
  const [watchResults, setWatchResults] = useState<Record<string, StudioLiveCheckResult>>({});
  // Memoized on its own serialized content (not object identity) so effects
  // keyed on it only re-run when the actual set of watched bundles changes,
  // never on every unrelated render.
  const watchBundleIds = useMemo(
    () => Array.from(watchDevices).map((device) => watchModelChoice[device]).filter((id): id is string => !!id),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [Array.from(watchDevices).sort().join(','), Object.entries(watchModelChoice).sort().join(',')],
  );

  // "Comprobacion de deteccion real" (automated baseline-vs-device-on check)
  const [healthPhase, setHealthPhase] = useState<HealthCheckPhase>('idle');
  const [healthSecondsLeft, setHealthSecondsLeft] = useState(0);
  const [healthVerdict, setHealthVerdict] = useState<HealthCheckVerdict | null>(null);
  const baselineSamplesRef = useRef<StudioLiveCheckResult[]>([]);
  const activeSamplesRef = useRef<StudioLiveCheckResult[]>([]);
  const [retraining, setRetraining] = useState(false);
  const [retrainJob, setRetrainJob] = useState<StudioJob | null>(null);
  const [retrainResult, setRetrainResult] = useState<StudioPrepareAndTrainSummary | null>(null);

  const inBleBand = isWithinBleBand(centerFrequencyHz, sampleRateHz);

  useEffect(() => {
    let cancelled = false;
    api.liveSelectableModels().then((list) => {
      if (!cancelled) setBundles(Array.isArray(list) ? list : []);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [open]);

  // Leaving the BLE band while a check is active must turn it off -- there
  // is no point (and it would be misleading) to keep reporting a stale BLE
  // device-detection result while tuned somewhere else, e.g. FM.
  useEffect(() => {
    if (activeBundleId && !inBleBand) {
      api.disableLiveMonitorCheck(activeBundleId).catch(() => {});
      setActiveBundleId(null);
      setDisplayedResult(null);
    }
    if (watchBundleIds.length && !inBleBand) {
      for (const bundleId of watchBundleIds) api.disableLiveMonitorCheck(bundleId).catch(() => {});
      setWatchDevices(new Set());
      setWatchModelChoice({});
      setWatchResults({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inBleBand]);

  // One shared poll drives both the single-select health-check flow
  // (activeBundleId) and the multi-device watch list -- a single
  // GET /live-monitor/result already returns every currently-watched
  // bundle's result keyed by bundle_id, so there is no reason to poll twice.
  useEffect(() => {
    if (!activeBundleId && watchBundleIds.length === 0) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const results = await api.liveMonitorResult();
        if (cancelled) return;
        if (watchBundleIds.length) {
          const next: Record<string, StudioLiveCheckResult> = {};
          for (const bundleId of watchBundleIds) if (results[bundleId]) next[bundleId] = results[bundleId];
          setWatchResults(next);
        }
        const latest = activeBundleId ? results[activeBundleId] : undefined;
        if (!latest) return;
        // Feed the automated health check, if one is currently collecting --
        // completely independent of the hold-time display logic below (the
        // check needs every raw sample, not the operator-friendly held view).
        if (healthPhase === 'baseline') baselineSamplesRef.current.push(latest);
        else if (healthPhase === 'active') activeSamplesRef.current.push(latest);

        const now = Date.now();
        if (latest.final_decision === 'IDENTIFIED') {
          heldAtRef.current = now;
          setDisplayedResult(latest);
        } else if (now - heldAtRef.current > holdSeconds * 1000) {
          // Hold window expired -- safe to show the current (possibly empty
          // or negative) state instead of the stale positive one.
          setDisplayedResult(latest);
        }
      } catch {
        // Transient poll failure -- keep showing the last known result
        // rather than flashing an error for a single missed request.
      }
    };
    poll();
    const interval = window.setInterval(poll, 1500);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [activeBundleId, watchBundleIds, holdSeconds, healthPhase]);

  // Load any previously-saved verdict for whichever bundle just became
  // active, so "los ultimos resultados reales" survive a page reload instead
  // of resetting to blank every time.
  useEffect(() => {
    setHealthPhase('idle');
    setHealthVerdict(activeBundleId ? loadStoredVerdict(activeBundleId) : null);
    setRetrainResult(null);
    setRetrainJob(null);
  }, [activeBundleId]);

  // Drives the 15s countdown for whichever phase is currently collecting,
  // then advances the state machine -- baseline -> prompt to turn the device
  // on -> active -> compute + persist the verdict.
  useEffect(() => {
    if (healthPhase !== 'baseline' && healthPhase !== 'active') return;
    setHealthSecondsLeft(HEALTH_CHECK_PHASE_SECONDS);
    const tick = window.setInterval(() => {
      setHealthSecondsLeft((seconds) => {
        if (seconds > 1) return seconds - 1;
        window.clearInterval(tick);
        if (healthPhase === 'baseline') {
          setHealthPhase('instructions_active');
        } else if (activeBundleId) {
          const verdict = computeVerdict(baselineSamplesRef.current, activeSamplesRef.current);
          storeVerdict(activeBundleId, verdict);
          setHealthVerdict(verdict);
          setHealthPhase('done');
        }
        return 0;
      });
    }, 1000);
    return () => window.clearInterval(tick);
  }, [healthPhase, activeBundleId]);

  const startHealthCheck = () => {
    baselineSamplesRef.current = [];
    activeSamplesRef.current = [];
    setHealthVerdict(null);
    setHealthPhase('instructions_baseline');
  };

  const retrainWithExistingCaptures = async () => {
    if (!activeBundleId) return;
    setRetraining(true);
    setError('');
    try {
      const reference = await api.retrainReference(activeBundleId);
      const job = await api.prepareAndTrain({ ...reference, speed_profile: 'normal' });
      setRetrainJob(job);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo lanzar el reentreno');
    } finally {
      setRetraining(false);
    }
  };

  useEffect(() => {
    if (!retrainJob || JOB_TERMINAL.has(retrainJob.state as string)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(retrainJob.job_id as string);
        setRetrainJob(next);
        if (JOB_TERMINAL.has(next.state as string)) {
          window.clearInterval(timer);
          if (next.state === 'completed') setRetrainResult((next.result_summary as unknown as StudioPrepareAndTrainSummary) ?? null);
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [retrainJob?.job_id, retrainJob?.state]);

  // Best-effort cleanup: whenever activeBundleId changes (switching to a
  // different single-select target, turning it off, or this panel going
  // away entirely) disable exactly the bundle THIS effect run captured --
  // never the blanket "disable everything" version, which would also stop
  // any bundle the multi-device watch list below has going.
  useEffect(() => () => { if (activeBundleId) api.disableLiveMonitorCheck(activeBundleId).catch(() => {}); }, [activeBundleId]);

  // Same for the watch list, and additionally on true unmount (page
  // navigation away from Live Monitor) -- nothing is left watching once
  // nobody can see the result anyway.
  useEffect(() => () => { for (const bundleId of watchBundleIds) api.disableLiveMonitorCheck(bundleId).catch(() => {}); }, [watchBundleIds]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const toggle = async (bundle: StudioLiveSelectableBundle) => {
    setError('');
    setBusy(true);
    try {
      if (activeBundleId === bundle.bundle_id) {
        await api.disableLiveMonitorCheck(bundle.bundle_id);
        setActiveBundleId(null);
        setDisplayedResult(null);
      } else {
        // Single-select semantics for the health-check flow: only one
        // bundle active here at a time. The backend itself is additive now
        // (multi-device watching below), so switching must explicitly
        // disable whichever bundle THIS flow had active before, never rely
        // on the backend to silently replace it (that would leave the
        // previous one running forever, invisibly).
        if (activeBundleId) await api.disableLiveMonitorCheck(activeBundleId);
        await api.enableLiveMonitorCheck(bundle.bundle_id);
        setActiveBundleId(bundle.bundle_id);
        setDisplayedResult(null);
        heldAtRef.current = 0;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo activar el modelo');
    } finally {
      setBusy(false);
    }
  };

  // "Vigilar varios dispositivos a la vez": one row per DEVICE (never one
  // per bundle -- a device with 5 trained model_type variants stays ONE
  // checkbox, not 5). Defaults to whichever of that device's models has the
  // lowest measured false-positive rate; the operator can override via the
  // per-row model dropdown without needing to uncheck/recheck.
  const defaultBundleForDevice = (models: StudioLiveSelectableBundle[]): StudioLiveSelectableBundle =>
    models.reduce((best, m) => {
      if (!best.reliability) return m.reliability ? m : best;
      if (!m.reliability) return best;
      return m.reliability.false_positive_rate_on_background < best.reliability.false_positive_rate_on_background ? m : best;
    }, models[0]);

  const toggleWatchDevice = async (device: string, models: StudioLiveSelectableBundle[]) => {
    setError('');
    setBusy(true);
    try {
      if (watchDevices.has(device)) {
        const bundleId = watchModelChoice[device];
        if (bundleId) await api.disableLiveMonitorCheck(bundleId);
        setWatchDevices((prev) => { const next = new Set(prev); next.delete(device); return next; });
        setWatchResults((prev) => { const next = { ...prev }; if (bundleId) delete next[bundleId]; return next; });
      } else {
        const chosen = models.find((m) => m.bundle_id === watchModelChoice[device]) || defaultBundleForDevice(models);
        await api.enableLiveMonitorCheck(chosen.bundle_id);
        setWatchModelChoice((prev) => ({ ...prev, [device]: chosen.bundle_id }));
        setWatchDevices((prev) => new Set(prev).add(device));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo activar el modelo');
    } finally {
      setBusy(false);
    }
  };

  // Switching which model_type a currently-watched device uses: disable the
  // old bundle, enable the new one -- if the device isn't watched yet, just
  // remember the preference for when it is.
  const changeWatchModel = async (device: string, newBundleId: string) => {
    if (!watchDevices.has(device)) {
      setWatchModelChoice((prev) => ({ ...prev, [device]: newBundleId }));
      return;
    }
    setError('');
    setBusy(true);
    try {
      const oldBundleId = watchModelChoice[device];
      if (oldBundleId && oldBundleId !== newBundleId) await api.disableLiveMonitorCheck(oldBundleId);
      await api.enableLiveMonitorCheck(newBundleId);
      setWatchModelChoice((prev) => ({ ...prev, [device]: newBundleId }));
      setWatchResults((prev) => { const next = { ...prev }; if (oldBundleId) delete next[oldBundleId]; return next; });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo cambiar el modelo');
    } finally {
      setBusy(false);
    }
  };

  // Delete an exported model right from Live Monitor -- the operator
  // shouldn't have to go back to BLE-RFFI Studio just to remove a bundle
  // they can already see (and select) here. Disables the live check first
  // if the bundle being removed is currently active in either flow, since a
  // deleted bundle can no longer be scored against.
  const deleteBundle = async (bundle: StudioLiveSelectableBundle) => {
    if (!window.confirm(`Borrar el modelo ${bundle.task_display || bundle.task} (${bundle.bundle_id})? No se puede deshacer.`)) return;
    setDeletingBundleId(bundle.bundle_id);
    setError('');
    try {
      if (activeBundleId === bundle.bundle_id) {
        await api.disableLiveMonitorCheck(bundle.bundle_id);
        setActiveBundleId(null);
        setDisplayedResult(null);
      }
      if (watchBundleIds.includes(bundle.bundle_id)) {
        const device = bundle.physical_units.length ? bundle.physical_units.join(' + ') : 'General';
        await api.disableLiveMonitorCheck(bundle.bundle_id);
        setWatchDevices((prev) => { const next = new Set(prev); next.delete(device); return next; });
        setWatchResults((prev) => { const next = { ...prev }; delete next[bundle.bundle_id]; return next; });
      }
      await api.deleteBundle(bundle.bundle_id);
      setBundles(await api.liveSelectableModels());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo borrar el modelo');
    } finally {
      setDeletingBundleId(null);
    }
  };

  const activeBundle = bundles.find((b) => b.bundle_id === activeBundleId) || null;

  // Band drawn directly on the spectrum, at the bundle's own training-time
  // channel/bandwidth -- same left%/width% frequency-to-pixel math
  // SpectrumView.tsx's own RF Experiment Lab overlay already uses for its
  // marker-band annotation (see the "Band annotation when live inference is
  // successful" block there), so this reads as one of the same family of
  // on-spectrum model overlays instead of a one-off.
  const band = (() => {
    if (!activeBundle) return null;
    const centerHz = activeBundle.acquisition_reference.center_frequency_hz;
    if (centerHz == null || !sampleRateHz) return null;
    const bandwidthHz = activeBundle.acquisition_reference.bandwidth_hz || sampleRateHz;
    const specStart = centerFrequencyHz - sampleRateHz / 2;
    const bandStart = centerHz - bandwidthHz / 2;
    const leftPct = ((bandStart - specStart) / sampleRateHz) * 100;
    const widthPct = (bandwidthHz / sampleRateHz) * 100;
    if (leftPct < -5 || leftPct + widthPct > 105 || widthPct < 0.1) return null;
    const clampedLeft = Math.max(0, leftPct);
    const clampedWidth = Math.min(100 - clampedLeft, widthPct);
    return { clampedLeft, clampedWidth };
  })();
  const identified = displayedResult?.final_decision === 'IDENTIFIED' && !displayedResult?.error;
  const liveHue = resultHue(displayedResult);

  // Same on-spectrum band mechanic as the single health-check model above,
  // but for every watched device at once: real request -- a detection must
  // be visible ON the spectrum itself, not only inside the dropdown list.
  // Devices that train on the same BLE channel (the common case: most of
  // this project's devices share channel 37) resolve to the same band
  // position, so they are grouped into ONE band with a small stacked list
  // of labels rather than several identical, overlapping rectangles.
  const watchBandGroups = useMemo(() => {
    if (!sampleRateHz) return [] as Array<{ left: number; width: number; devices: Array<{ device: string; hue: number; text: string }> }>;
    const specStart = centerFrequencyHz - sampleRateHz / 2;
    const groups = new Map<string, { left: number; width: number; devices: Array<{ device: string; hue: number; text: string }> }>();
    for (const device of watchDevices) {
      const bundleId = watchModelChoice[device];
      const bundle = bundles.find((b) => b.bundle_id === bundleId);
      const centerHz = bundle?.acquisition_reference.center_frequency_hz;
      if (!bundle || centerHz == null) continue;
      const bandwidthHz = bundle.acquisition_reference.bandwidth_hz || sampleRateHz;
      const bandStart = centerHz - bandwidthHz / 2;
      const leftPct = ((bandStart - specStart) / sampleRateHz) * 100;
      const widthPct = (bandwidthHz / sampleRateHz) * 100;
      if (leftPct < -5 || leftPct + widthPct > 105 || widthPct < 0.1) continue;
      const clampedLeft = Math.max(0, leftPct);
      const clampedWidth = Math.min(100 - clampedLeft, widthPct);
      const result = watchResults[bundleId];
      const isIdentified = result?.final_decision === 'IDENTIFIED' && !result.error;
      const hue = isIdentified ? 120 : 0;
      const text = isIdentified
        ? `${device} · ${result?.class_probability != null ? `${Math.round((result.class_probability as number) * 100)}%` : 'identificado'}`
        : `${device} · vigilando`;
      const key = `${clampedLeft.toFixed(1)}_${clampedWidth.toFixed(1)}`;
      const existing = groups.get(key);
      if (existing) existing.devices.push({ device, hue, text });
      else groups.set(key, { left: clampedLeft, width: clampedWidth, devices: [{ device, hue, text }] });
    }
    return Array.from(groups.values());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchDevices, watchModelChoice, watchResults, bundles, centerFrequencyHz, sampleRateHz]);

  return (
    <>
      {band && (
        <div className="pointer-events-none absolute inset-0 z-[10]">
          <div
            className="absolute top-0 bottom-0 border-l border-r transition-colors"
            style={{ left: `${band.clampedLeft}%`, width: `${band.clampedWidth}%`, borderColor: hsl(liveHue, 0.5), backgroundColor: hsl(liveHue, 0.08) }}
          >
            <div
              className="absolute top-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md border bg-slate-950/85 px-2 py-0.5 text-[10px] backdrop-blur-sm shadow"
              style={{ borderColor: hsl(liveHue, 0.4), color: hsl(liveHue) }}
            >
              {(activeBundle!.physical_units.join(' + ') || 'General')} · {MODEL_TYPE_LABELS[activeBundle!.model_type || ''] || activeBundle!.model_type}
              {' '}· {identified ? (displayedResult!.identified_device || displayedResult!.predicted_class) : 'No detectado'}
              {identified && displayedResult!.class_probability != null ? ` · ${Math.round(displayedResult!.class_probability * 100)}%` : ''}
            </div>
          </div>
        </div>
      )}
      {watchBandGroups.length > 0 && (
        <div className="pointer-events-none absolute inset-0 z-[9]">
          {watchBandGroups.map((group, i) => (
            <div
              key={i}
              className="absolute top-0 bottom-0 border-l border-r border-dashed transition-colors"
              style={{ left: `${group.left}%`, width: `${group.width}%`, borderColor: 'rgba(148,163,184,0.35)' }}
            >
              <div className="absolute top-9 left-1/2 flex -translate-x-1/2 flex-col items-center gap-0.5">
                {group.devices.map((d) => (
                  <div
                    key={d.device}
                    className="whitespace-nowrap rounded-md border bg-slate-950/85 px-2 py-0.5 text-[10px] backdrop-blur-sm shadow"
                    style={{ borderColor: hsl(d.hue, 0.4), color: hsl(d.hue) }}
                  >
                    {d.text}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <div ref={rootRef} className="absolute right-60 top-2 z-20 w-fit pointer-events-auto" onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="whitespace-nowrap rounded-md border border-slate-600 bg-slate-950/90 px-3 py-2 text-xs font-semibold text-slate-100 shadow-lg backdrop-blur"
      >
        BLE-RFFI Studio{(activeBundleId ? 1 : 0) + watchBundleIds.length > 0 ? ` · ${(activeBundleId ? 1 : 0) + watchBundleIds.length}` : ''} ▾
      </button>
      {open && (
        // Capped against the viewport on both axes (not just height) --
        // w-[26rem] alone could overflow past the left edge of a narrower
        // spectrum panel (e.g. sidebar open, smaller window), which pushed
        // this dropdown outside its positioning container instead of
        // wrapping/scrolling inside it. overflow-y-auto keeps the list
        // scrollable internally rather than growing the box further.
        <div className="mt-2 max-h-[60vh] w-[min(26rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-slate-700 bg-slate-950/95 p-3 shadow-2xl backdrop-blur">
          {!inBleBand && (
            <div className="mb-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-200">
              Sintoniza un canal BLE (ej. 2402 MHz) para activar un modelo.
            </div>
          )}
          {bundles.length === 0 ? (
            <div className="text-[11px] text-slate-500">Todavia no hay modelos BLE-RFFI aprobados para monitoreo en vivo.</div>
          ) : (
            <>
              <div className="mb-2 text-[11px] text-slate-400">Tenemos modelos para identificar:</div>
              {Object.entries(groupByDevice(bundles)).map(([device, models]) => (
                <div key={device} className="mb-2 last:mb-0">
                  <div className="mb-1 text-xs font-semibold text-slate-200">{device}</div>
                  {models.map((bundle) => (
                    <label
                      key={bundle.bundle_id}
                      className={`flex items-center gap-2 rounded-md px-2 py-1.5 ${!inBleBand ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-slate-800'}`}
                    >
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: activeBundleId === bundle.bundle_id ? '#34d399' : '#64748b' }} />
                      <span className="min-w-0 flex-1 text-[13px] text-slate-100">{bundle.task_display || bundle.task}</span>
                      {bundle.model_type && (
                        <span className="shrink-0 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                          {MODEL_TYPE_LABELS[bundle.model_type] || bundle.model_type}
                        </span>
                      )}
                      {bundle.reliability && (() => {
                        const fpr = bundle.reliability.false_positive_rate_on_background;
                        const tone = fpr >= 0.5 ? 'bg-rose-950/60 text-rose-300' : fpr >= 0.15 ? 'bg-amber-950/60 text-amber-300' : 'bg-emerald-950/40 text-emerald-300';
                        return (
                          <span
                            className={`shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] ${tone}`}
                            title={`En datos de prueba reales, este modelo dice "dispositivo presente" el ${(fpr * 100).toFixed(0)}% de las veces cuando en realidad estaba ausente (falso positivo). Precision real al identificar el dispositivo: ${(bundle.reliability.target_device_precision * 100).toFixed(0)}%.`}
                          >
                            FP {(fpr * 100).toFixed(0)}%
                          </span>
                        );
                      })()}
                      <input
                        type="checkbox"
                        className="shrink-0"
                        checked={activeBundleId === bundle.bundle_id}
                        disabled={!inBleBand || busy}
                        onChange={() => toggle(bundle)}
                      />
                      <button
                        type="button"
                        aria-label={`Eliminar modelo ${bundle.task_display || bundle.task}`}
                        title="Eliminar este modelo exportado"
                        className="shrink-0 rounded px-1 text-[13px] text-slate-500 hover:bg-rose-950/60 hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-40"
                        disabled={deletingBundleId === bundle.bundle_id}
                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); void deleteBundle(bundle); }}
                      >
                        {deletingBundleId === bundle.bundle_id ? '…' : '×'}
                      </button>
                    </label>
                  ))}
                </div>
              ))}
              <label className="mt-2 flex items-center gap-2 border-t border-slate-800 pt-2 text-[11px] text-slate-400">
                Retener resultado (s)
                <input
                  type="number" min={1} max={30} value={holdSeconds}
                  onChange={(e) => setHoldSeconds(Math.max(1, Number(e.target.value) || DEFAULT_HOLD_SECONDS))}
                  className="w-14 rounded bg-slate-900 px-2 py-0.5 text-slate-100"
                  title="Cuanto tiempo se mantiene visible una identificacion positiva antes de volver a 'esperando' -- el live varia rapido y una deteccion real puede pasar desapercibida si se reemplaza al instante."
                />
              </label>

              <div className="mt-2 border-t border-slate-800 pt-2">
                <div className="mb-1 text-xs font-semibold text-slate-200">
                  Vigilar varios dispositivos a la vez{watchDevices.size ? ` (${watchDevices.size})` : ''}
                </div>
                <div className="mb-1 text-[10px] text-slate-500">
                  Un dispositivo, un modelo cada vez -- todos comparten la misma señal en vivo (nunca se vuelve a capturar por modelo). Util para ver cual dispositivo, si alguno, esta encendido ahora mismo.
                </div>

                {/* Compact summary: one small chip per watched device, never
                    grows the panel beyond a single wrapped line regardless
                    of how many devices are being watched. */}
                {watchDevices.size > 0 && (
                  <div className="mb-2 flex flex-wrap gap-1">
                    {Array.from(watchDevices).map((device) => {
                      const bundleId = watchModelChoice[device];
                      const result = bundleId ? watchResults[bundleId] : undefined;
                      const identified = result?.final_decision === 'IDENTIFIED' && !result.error;
                      return (
                        <span
                          key={device}
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${identified ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'}`}
                        >
                          {identified ? '● ' : '○ '}{device}
                        </span>
                      );
                    })}
                  </div>
                )}

                {Object.entries(groupByDevice(bundles)).map(([device, models]) => {
                  const watching = watchDevices.has(device);
                  const chosenBundleId = watchModelChoice[device] || defaultBundleForDevice(models).bundle_id;
                  const result = watching ? watchResults[chosenBundleId] : undefined;
                  const identified = watching && result?.final_decision === 'IDENTIFIED' && !result.error;
                  return (
                    <div
                      key={device}
                      className={`flex items-center gap-2 rounded-md px-2 py-1 ${!inBleBand ? 'opacity-50' : ''}`}
                    >
                      <input
                        type="checkbox"
                        className="shrink-0"
                        checked={watching}
                        disabled={!inBleBand || busy}
                        onChange={() => toggleWatchDevice(device, models)}
                      />
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: identified ? '#34d399' : watching ? '#64748b' : '#334155' }} />
                      <span className="min-w-0 flex-1 truncate text-[12px] text-slate-200">{device}</span>
                      {models.length > 1 ? (
                        <select
                          className="shrink-0 rounded bg-slate-800 px-1 py-0.5 text-[10px] text-slate-300"
                          value={chosenBundleId}
                          disabled={busy}
                          onChange={(e) => changeWatchModel(device, e.target.value)}
                        >
                          {models.map((m) => <option key={m.bundle_id} value={m.bundle_id}>{MODEL_TYPE_LABELS[m.model_type || ''] || m.model_type}</option>)}
                        </select>
                      ) : (
                        <span className="shrink-0 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                          {MODEL_TYPE_LABELS[models[0].model_type || ''] || models[0].model_type}
                        </span>
                      )}
                      {watching && (
                        // A separate pill, not inline text right after the
                        // device name -- "entorno" flowing directly after
                        // "CC2650-UNIT-01" read like it was describing the
                        // device itself ("CC2650-UNIT-01 [es] entorno")
                        // instead of reporting this device's current
                        // detection state. AUSENTE is unambiguous either way.
                        <span
                          className={`shrink-0 whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${
                            identified ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-slate-700 bg-slate-900 text-slate-500'
                          }`}
                        >
                          {identified
                            ? `PRESENTE${result?.class_probability != null ? ` ${Math.round((result.class_probability as number) * 100)}%` : ''}`
                            : (result ? 'AUSENTE' : 'esperando…')}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>

              {activeBundle && (
                <div className="mt-2 border-t border-slate-800 pt-2">
                  <div className="mb-1 text-xs font-semibold text-slate-200">Comprobacion de deteccion real</div>

                  {healthPhase === 'idle' && (
                    <>
                      {healthVerdict && (
                        <div className={`mb-2 rounded-md border p-2 text-[11px] ${healthVerdict.passed ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' : 'border-rose-500/30 bg-rose-500/10 text-rose-200'}`}>
                          <div className="font-semibold">
                            {healthVerdict.passed ? 'Ultima comprobacion: el modelo SI distingue tu dispositivo.' : 'Ultima comprobacion: el modelo NO distingue tu dispositivo de forma fiable.'}
                          </div>
                          <div className="mt-0.5 opacity-80">
                            Sin dispositivo: identificado {Math.round(healthVerdict.baselineRate * 100)}% del tiempo (confianza media {Math.round(healthVerdict.baselineMean * 100)}%).
                            {' '}Con dispositivo: {Math.round(healthVerdict.activeRate * 100)}% (confianza media {Math.round(healthVerdict.activeMean * 100)}%).
                          </div>
                          <div className="mt-0.5 opacity-60">{new Date(healthVerdict.ranAt).toLocaleString()}</div>
                          {!healthVerdict.passed && (
                            <div className="mt-1 opacity-90">
                              Recomendacion: captura al menos 3 sesiones mas de "Dispositivo encendido" y 3 mas de "Entorno" (dispositivo apagado/retirado) en BLE-RFFI Studio, y reentrena.
                            </div>
                          )}
                        </div>
                      )}
                      <button type="button" className="w-full rounded-md bg-slate-800 px-2 py-1.5 text-[11px] text-slate-200 hover:bg-slate-700" onClick={startHealthCheck}>
                        {healthVerdict ? 'Volver a comprobar' : 'Comprobar si detecta de verdad (~30s)'}
                      </button>
                    </>
                  )}

                  {healthPhase === 'instructions_baseline' && (
                    <div className="rounded-md border border-cyan-500/30 bg-cyan-500/10 p-2 text-[11px] text-cyan-100">
                      <div className="font-semibold">Paso 1 de 2</div>
                      <div className="mt-1">Asegurate de que TU dispositivo este APAGADO ahora mismo. Cuando estes listo, pulsa Empezar.</div>
                      <button type="button" className="mt-2 w-full rounded-md bg-cyan-700 px-2 py-1.5 font-semibold text-white hover:bg-cyan-600" onClick={() => setHealthPhase('baseline')}>
                        Empezar ({HEALTH_CHECK_PHASE_SECONDS}s)
                      </button>
                    </div>
                  )}

                  {healthPhase === 'baseline' && (
                    <div className="rounded-md border border-cyan-500/30 bg-cyan-500/10 p-2 text-[11px] text-cyan-100">
                      Midiendo el entorno (dispositivo apagado)... {healthSecondsLeft}s
                    </div>
                  )}

                  {healthPhase === 'instructions_active' && (
                    <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-100">
                      <div className="font-semibold">Paso 2 de 2</div>
                      <div className="mt-1">Ahora ENCIENDE tu dispositivo. Cuando lo hayas hecho, pulsa Continuar.</div>
                      <button type="button" className="mt-2 w-full rounded-md bg-emerald-700 px-2 py-1.5 font-semibold text-white hover:bg-emerald-600" onClick={() => setHealthPhase('active')}>
                        Continuar ({HEALTH_CHECK_PHASE_SECONDS}s)
                      </button>
                    </div>
                  )}

                  {healthPhase === 'active' && (
                    <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-100">
                      Midiendo con el dispositivo encendido... {healthSecondsLeft}s
                    </div>
                  )}

                  {healthPhase === 'done' && healthVerdict && (
                    <div className={`rounded-md border p-2 text-[11px] ${healthVerdict.passed ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' : 'border-rose-500/30 bg-rose-500/10 text-rose-200'}`}>
                      <div className="font-semibold">
                        {healthVerdict.passed ? 'SI, el modelo distingue tu dispositivo.' : 'NO, el modelo no distingue tu dispositivo de forma fiable.'}
                      </div>
                      <div className="mt-0.5 opacity-80">
                        Sin dispositivo: identificado {Math.round(healthVerdict.baselineRate * 100)}% del tiempo (confianza media {Math.round(healthVerdict.baselineMean * 100)}%).
                        {' '}Con dispositivo: {Math.round(healthVerdict.activeRate * 100)}% (confianza media {Math.round(healthVerdict.activeMean * 100)}%).
                      </div>
                      {healthVerdict.passed ? (
                        <div className="mt-1 opacity-90">No hace falta capturar mas ni reentrenar por ahora.</div>
                      ) : (
                        <>
                          <div className="mt-1 opacity-90">
                            Recomendacion: captura al menos 3 sesiones mas de "Dispositivo encendido" y 3 mas de "Entorno" (dispositivo apagado/retirado) en BLE-RFFI Studio, y reentrena.
                          </div>
                          {!retrainJob && (
                            <button type="button" disabled={retraining} className="mt-2 w-full rounded-md bg-rose-800 px-2 py-1.5 font-semibold text-white hover:bg-rose-700 disabled:opacity-50" onClick={retrainWithExistingCaptures}>
                              {retraining ? 'Lanzando reentreno...' : 'Reentrenar con las capturas ya existentes'}
                            </button>
                          )}
                        </>
                      )}
                      <button type="button" className="mt-2 w-full rounded-md bg-slate-800 px-2 py-1.5 text-slate-200 hover:bg-slate-700" onClick={() => setHealthPhase('idle')}>
                        Cerrar
                      </button>
                    </div>
                  )}

                  {retrainJob && !JOB_TERMINAL.has(retrainJob.state as string) && (
                    <div className="mt-2 rounded-md border border-slate-700 bg-slate-900/60 p-2 text-[11px] text-slate-300">
                      Reentrenando... {String(retrainJob.message || retrainJob.state)}
                    </div>
                  )}
                  {retrainJob && retrainJob.state === 'failed' && (
                    <div className="mt-2 rounded-md border border-rose-500/30 bg-rose-500/10 p-2 text-[11px] text-rose-200">
                      El reentreno fallo: {String(retrainJob.error || 'motivo desconocido')}
                    </div>
                  )}
                  {retrainResult && (
                    <div className="mt-2 rounded-md border border-cyan-500/30 bg-cyan-500/10 p-2 text-[11px] text-cyan-100">
                      {retrainResult.recommended_training_run_id
                        ? <>Reentreno listo: modelo recomendado {retrainResult.trained_models.find((m) => m.training_run_id === retrainResult.recommended_training_run_id)?.model_type}. Ve a BLE-RFFI Studio (Paso 6) para exportarlo y aprobarlo.</>
                        : <>Reentreno completado, pero ningun modelo alcanzo la calidad minima todavia -- sigue capturando mas sesiones.</>}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
          {error && <div className="mt-2 text-[11px] text-rose-300">{error}</div>}
        </div>
      )}
      {activeBundle && (
        <div className="mt-2 flex max-w-[420px] flex-wrap gap-1.5 pointer-events-auto">
          <div className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-950/80 px-2 py-1 text-[11px] text-slate-100 shadow backdrop-blur">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: hsl(liveHue) }} />
            <span className="text-slate-400">
              {(activeBundle.physical_units.join(' + ') || 'General')} · {MODEL_TYPE_LABELS[activeBundle.model_type || ''] || activeBundle.model_type}:
            </span>
            {displayedResult?.error ? (
              <span className="text-amber-300">{displayedResult.error}</span>
            ) : identified ? (
              <span className="font-semibold" style={{ color: hsl(liveHue) }}>
                {displayedResult!.identified_device || displayedResult!.predicted_class} · {displayedResult!.class_probability != null ? `${Math.round(displayedResult!.class_probability * 100)}%` : '--'}
              </span>
            ) : (
              <span style={{ color: hsl(0) }}>No detectado</span>
            )}
            <button type="button" aria-label="Desactivar verificacion en vivo" onClick={() => toggle(activeBundle)} className="rounded px-1 hover:bg-slate-700">×</button>
          </div>
        </div>
      )}
      </div>
    </>
  );
}
