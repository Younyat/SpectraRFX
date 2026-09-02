import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Menu as MenuIcon, Maximize2, Minimize2 } from 'lucide-react';
import { detectWebGLSupport } from '../model/rfTerrainCapabilities';
import { useRFTerrainFrameSource } from '../data/useRFTerrainFrameSource';
import { RFTerrainCanvas, RFTerrainCanvasHandle, RFTerrainColorSource, RFTerrainOverlayToggles, RFTerrainTraceSource, RFTerrainTraceScope } from './RFTerrainCanvas';
import { RFTerrainFallback2D } from './RFTerrainFallback2D';
import { RFTerrainToolbar, RFTerrainFrequencyInfo } from './RFTerrainToolbar';
import { RFTerrainHudBadges } from './RFTerrainHudBadges';
import { HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND } from './hud/hudTheme';
import { RFTerrainOverlaysPanel } from './RFTerrainOverlaysPanel';
import { RFTerrainReceiverControls } from './RFTerrainReceiverControls';
import { RFTerrainPanControl } from './RFTerrainPanControl';
import { RFTerrainProfilesPanel } from './RFTerrainProfilesPanel';
import { RFTerrainLegend } from './RFTerrainLegend';
import { RFTerrainStatus } from './RFTerrainStatus';
import { RFTerrainInspector } from './RFTerrainInspector';
import { RFTerrainOfflinePanel, RFTerrainSource } from './RFTerrainOfflinePanel';
import { RFTerrainOfflineMonitor } from './RFTerrainOfflineMonitor';
import { RFTerrainAiPluginPanel } from './RFTerrainAiPluginPanel';
import { RUNTIME_CONFIG } from '../../../shared/config/runtime';
import { useOfflineReconstruction } from '../offline/useOfflineReconstruction';
import { useAiLiveDetection } from '../ai/useAiLiveDetection';
import { OFFLINE_RECONSTRUCTION_PROFILE_V1 } from '../engine/offline/reconstructionProfile';
import type { SourceEvidence } from '../offline/sourceEvidence';
import { RF_TERRAIN_POLL_INTERVAL_MS, RF_TERRAIN_REWIND_MAX_OFFSET_ROWS } from '../model/rfTerrainConstants';
import type { RFTerrainCameraPreset, RFTerrainMode, TerrainInspectorSelection, TerrainObject, TerrainProcessedRow } from '../model/rfTerrainTypes';
import type { TerrainColormap } from '../render/TerrainColors';

const NO_OVERLAYS: RFTerrainOverlayToggles = {
  maxHold: false, minHold: false, average: false, ewma: false,
  p50: false, p90: false, p95: false, p99: false,
  historyWireframe: false, frequencyMarker: true,
};

const triggerDownload = (href: string, filename: string) => {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  link.click();
};

// PR3-PR6 -- RAW/Adaptive/Occupancy Three.js terrain, ARST core (noise
// floor, excess, persistence, occupancy, holds, average), click inspector,
// freeze/reset, terrain-object segmentation, a bounded rewind window and a
// collapsible overlays panel, composed together. All of it sits behind
// RFTerrainModuleBoundary + the module's own error boundary (spec §51) and
// the WebGL/Worker fail-closed paths below -- a failure here degrades only
// this module.
export const RFTerrainView: React.FC = () => {
  const capability = useMemo(() => detectWebGLSupport(), []);
  const canvasRef = useRef<RFTerrainCanvasHandle>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);

  const [mode, setMode] = useState<RFTerrainMode>('adaptive');
  const [colorSource, setColorSource] = useState<RFTerrainColorSource>('magnitude');
  // What feeds the terrain (live vs Max/Min Hold, Average, EWMA,
  // P50-P99) and how far that choice reaches -- only new rows going
  // forward ('liveEdgeOnly', the default) or a retroactive repaint of
  // every currently-visible row from its own real cached value
  // ('entireHistory').
  const [traceSource, setTraceSource] = useState<RFTerrainTraceSource>('live');
  const [traceScope, setTraceScope] = useState<RFTerrainTraceScope>('liveEdgeOnly');
  const [cameraPreset, setCameraPreset] = useState<RFTerrainCameraPreset>('3d');
  const [colormapName, setColormapName] = useState<TerrainColormap>('turbo');
  // Terrain-object segmentation itself always runs (selection must keep
  // working even with this off) -- this only controls whether the
  // Inspector's "Objects (N)" list is shown, purely a display preference.
  const [objectsEnabled, setObjectsEnabled] = useState(false);
  const [overlays, setOverlays] = useState<RFTerrainOverlayToggles>(NO_OVERLAYS);
  const [menuOpen, setMenuOpen] = useState(false);
  const [overlaysPanelOpen, setOverlaysPanelOpen] = useState(false);
  const [receiverControlsOpen, setReceiverControlsOpen] = useState(false);
  const [panControlOpen, setPanControlOpen] = useState(false);
  const [profilesPanelOpen, setProfilesPanelOpen] = useState(false);
  const [offlinePanelOpen, setOfflinePanelOpen] = useState(false);
  const [aiPluginPanelOpen, setAiPluginPanelOpen] = useState(false);
  // What feeds the terrain right now: the connected SDR in real time, or a
  // reconstructed preserved capture. Mutually exclusive -- only one
  // source's rows ever reach the canvas at a time (its onRow callback
  // below is the only place either path touches applyRow/frequencyInfo).
  const [source, setSource] = useState<RFTerrainSource>('LIVE');
  const [maskThresholdDb, setMaskThresholdDb] = useState<number | null>(null);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(true);
  const [frozen, setFrozen] = useState(false);
  const [viewOffsetRows, setViewOffsetRows] = useState(0);
  const [selection, setSelection] = useState<TerrainInspectorSelection | null>(null);
  const [objects, setObjects] = useState<TerrainObject[]>([]);
  const [fps, setFps] = useState(0);
  const [contextLost, setContextLost] = useState(false);
  const [frequencyInfo, setFrequencyInfo] = useState<RFTerrainFrequencyInfo | null>(null);

  const { diagnostics, resetTerrain } = useRFTerrainFrameSource({
    enabled: capability.supported && source === 'LIVE',
    frozen,
    onRow: (row: TerrainProcessedRow) => {
      canvasRef.current?.applyRow(row);
      setFrequencyInfo({
        centerFrequencyHz: row.frame.centerFrequency,
        spanHz: row.frame.span,
        sampleRateHz: row.frame.sampleRateHz,
        effectiveRbwHz: row.frame.effectiveRbwHz,
        powerUnit: row.frame.powerUnit,
        deviceSerial: row.frame.deviceSerial,
        calibrationId: row.frame.calibrationId,
      });
    },
    onObjects: setObjects,
    onReset: () => {
      canvasRef.current?.clear();
      setSelection(null);
      setObjects([]);
      setViewOffsetRows(0);
    },
  });

  // Offline Spectral Reconstruction (additive, spec §6-7): its own
  // controller instance, its own in-process engine -- feeds the SAME
  // canvas via the SAME applyRow()/clear() calls LIVE uses above, never
  // touched while source === 'LIVE'.
  const offline = useOfflineReconstruction({
    onRow: (row: TerrainProcessedRow) => {
      canvasRef.current?.applyRow(row);
      setFrequencyInfo({
        centerFrequencyHz: row.frame.centerFrequency,
        spanHz: row.frame.span,
        sampleRateHz: row.frame.sampleRateHz,
        effectiveRbwHz: row.frame.effectiveRbwHz,
        powerUnit: row.frame.powerUnit,
        deviceSerial: row.frame.deviceSerial,
        calibrationId: row.frame.calibrationId,
      });
    },
    onReset: () => {
      canvasRef.current?.clear();
      setSelection(null);
      setViewOffsetRows(0);
    },
  });

  // AI Research Plugin continuous LIVE detection (additive): its own
  // controller, no dependency on offline/LIVE terrain state beyond the
  // real, currently-tuned frequencyInfo it needs for applicability
  // gating. Called unconditionally (like offline above) so it keeps
  // running -- and keeps feeding the 3D overlay -- after the FSEI panel
  // closes, mirroring exactly how offline.state.objects stays visible
  // after OFFLINE RECONSTRUCTION's panel closes.
  const aiLiveDetection = useAiLiveDetection({
    frequencyInfo,
    onDetection: (detection) => canvasRef.current?.addAiDetection(detection),
  });

  // Once a reconstruction finishes, its (also real, segmented-once)
  // objects become the ones the Inspector/canvas can select -- mirrors
  // LIVE's onObjects, just sourced from the completed run instead of a
  // recurring SEGMENT tick.
  useEffect(() => {
    if (source === 'OFFLINE') {
      setObjects(offline.state.objects);
    }
  }, [source, offline.state.objects]);

  // Switching source is a hard visual reset -- the two feeds are never
  // blended in one terrain (spec: LIVE and OFFLINE stay strictly
  // separate). Any OFFLINE reconstruction already in flight keeps running
  // in the background and is still there when the operator switches back.
  useEffect(() => {
    canvasRef.current?.clear();
    setSelection(null);
    setViewOffsetRows(0);
    if (source === 'LIVE') {
      setObjects([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately fires only on source changes
  }, [source]);

  const sourceEvidence: SourceEvidence | null = useMemo(() => {
    if (source !== 'OFFLINE' || !offline.state.metadata) return null;
    return {
      captureId: offline.state.metadata.captureId,
      dataSha256: offline.state.metadata.dataSha256,
      sampleRateSps: offline.state.metadata.sampleRateSps,
      fftSize: OFFLINE_RECONSTRUCTION_PROFILE_V1.fftSize,
    };
  }, [source, offline.state.metadata]);

  // Stays in sync with the browser's own fullscreen state too (e.g. the
  // operator pressing Esc natively) -- never just trusts our own toggle.
  useEffect(() => {
    const handleChange = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', handleChange);
    return () => document.removeEventListener('fullscreenchange', handleChange);
  }, []);

  if (!capability.supported) {
    return <RFTerrainFallback2D />;
  }

  // Real browser Fullscreen API when available (removes browser chrome
  // too), PLUS an in-app "fill the whole viewport" CSS fallback that
  // always works regardless of Fullscreen API support/permission -- the
  // spectrum genuinely occupies the whole screen either way.
  const toggleFullscreen = async () => {
    if (!fullscreen) {
      try {
        await rootRef.current?.requestFullscreen?.();
      } catch {
        // Fullscreen API unavailable/denied -- the CSS fallback below
        // still delivers a full-viewport view.
      }
      setFullscreen(true);
    } else {
      try {
        if (document.fullscreenElement) {
          await document.exitFullscreen();
        }
      } catch {
        // Ignore -- still drop out of the CSS fallback state below.
      }
      setFullscreen(false);
    }
  };

  // Click mountain -> gold selection -> HUD opens, in one action. Never
  // force it closed again on deselect -- that would fight an operator who
  // deliberately collapsed it while still reviewing the last selection.
  const handleSelect = (next: TerrainInspectorSelection | null) => {
    setSelection(next);
    if (next) {
      setInspectorCollapsed(false);
    }
  };

  const handleViewOffsetChange = (offsetRows: number) => {
    setViewOffsetRows(offsetRows);
    canvasRef.current?.setViewOffset(offsetRows);
    setSelection(null);
  };

  const handleExportPng = () => {
    const dataUrl = canvasRef.current?.exportPng();
    if (dataUrl) triggerDownload(dataUrl, `rf-terrain-${Date.now()}.png`);
  };

  const handleExportCsv = () => {
    const csv = canvasRef.current?.exportCsv();
    if (!csv) return;
    triggerDownload(`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`, `rf-terrain-${Date.now()}.csv`);
  };

  return (
    <div
      ref={rootRef}
      className={fullscreen ? 'fixed inset-0 z-[200] flex h-screen w-screen flex-col bg-[#050810]' : 'flex h-full w-full flex-col'}
    >
      <RFTerrainToolbar
        frequencyInfo={frequencyInfo}
        cameraPreset={cameraPreset}
        onCameraPresetChange={(preset) => { setCameraPreset(preset); canvasRef.current?.setCameraPreset(preset); }}
        frozen={frozen}
        onFrozenToggle={() => setFrozen((prev) => !prev)}
        onReset={resetTerrain}
        viewOffsetRows={viewOffsetRows}
        maxOffsetRows={RF_TERRAIN_REWIND_MAX_OFFSET_ROWS}
        onViewOffsetChange={handleViewOffsetChange}
        pollIntervalMs={RF_TERRAIN_POLL_INTERVAL_MS}
      />
      <div className="relative min-h-0 flex-1">
        <RFTerrainCanvas
          ref={canvasRef}
          mode={mode}
          colormapName={colormapName}
          colorSource={colorSource}
          traceSource={traceSource}
          traceScope={traceScope}
          objects={objects}
          overlays={overlays}
          maskThresholdDb={maskThresholdDb}
          onSelect={handleSelect}
          onFpsUpdate={setFps}
          onContextLost={() => setContextLost(true)}
          onContextRestored={() => setContextLost(false)}
        />

        <RFTerrainHudBadges frequencyInfo={frequencyInfo} lastFrameTimestamp={diagnostics.lastFrameTimestamp} selection={selection} />

        {/* Always visible while reconstructing, independent of whether the
            Menu/Offline panel happens to be open -- precise time/progress
            monitoring shouldn't require keeping a side panel open. */}
        {source === 'OFFLINE' && <RFTerrainOfflineMonitor state={offline.state} />}

        <button
          onClick={toggleFullscreen}
          title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          className="pointer-events-auto absolute right-3 top-3 z-30 flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
          style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
        >
          {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </button>

        {/* Single collapsible "Menu" trigger (spec-adjacent request): Layers /
            Pan / Receiver / Profiles stay hidden -- and their own panels
            force-closed -- until Menu is opened, so the default view stays
            uncluttered. */}
        <button
          onClick={() => setMenuOpen((prev) => !prev)}
          className="pointer-events-auto absolute left-3 top-3 z-30 flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-cyan-100 backdrop-blur transition-colors hover:text-cyan-50"
          style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND, boxShadow: HUD_GLOW_SHADOW }}
        >
          <MenuIcon className="h-3.5 w-3.5" />
          Menu
        </button>

        {menuOpen && (
          <>
            <RFTerrainOverlaysPanel
              open={overlaysPanelOpen}
              onToggleOpen={() => setOverlaysPanelOpen((prev) => !prev)}
              mode={mode}
              onModeChange={setMode}
              colormapName={colormapName}
              onColormapChange={setColormapName}
              colorSource={colorSource}
              onColorSourceChange={setColorSource}
              traceSource={traceSource}
              onTraceSourceChange={setTraceSource}
              traceScope={traceScope}
              onTraceScopeChange={setTraceScope}
              overlays={overlays}
              onOverlaysChange={setOverlays}
              objectsEnabled={objectsEnabled}
              onObjectsEnabledChange={setObjectsEnabled}
              maskThresholdDb={maskThresholdDb}
              onMaskThresholdChange={setMaskThresholdDb}
            />
            <RFTerrainReceiverControls
              open={receiverControlsOpen}
              onToggleOpen={() => setReceiverControlsOpen((prev) => !prev)}
              onExportPng={handleExportPng}
              onExportCsv={handleExportCsv}
            />
            <RFTerrainPanControl open={panControlOpen} onToggleOpen={() => setPanControlOpen((prev) => !prev)} />
            <RFTerrainProfilesPanel open={profilesPanelOpen} onToggleOpen={() => setProfilesPanelOpen((prev) => !prev)} />
            <RFTerrainOfflinePanel
              open={offlinePanelOpen}
              onToggleOpen={() => setOfflinePanelOpen((prev) => !prev)}
              source={source}
              onSourceChange={setSource}
              controller={offline.controller}
              state={offline.state}
            />
            {RUNTIME_CONFIG.aiResearchPluginEnabled && (
              <RFTerrainAiPluginPanel
                open={aiPluginPanelOpen}
                onToggleOpen={() => setAiPluginPanelOpen((prev) => !prev)}
                liveDetection={aiLiveDetection}
              />
            )}
          </>
        )}

        <RFTerrainLegend mode={mode} colorSource={colorSource} />
        <RFTerrainInspector
          selection={selection}
          objects={objects}
          showObjectsList={objectsEnabled}
          collapsed={inspectorCollapsed}
          onToggleCollapsed={() => setInspectorCollapsed((prev) => !prev)}
          onUnpin={() => canvasRef.current?.unpinSelection()}
          sourceEvidence={sourceEvidence}
        />
        {contextLost && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/60 text-sm text-amber-300">
            WebGL context lost -- attempting recovery. The rest of SpectraRFX keeps working.
          </div>
        )}
      </div>
      <RFTerrainStatus diagnostics={diagnostics} fps={fps} webglVersion={capability.version} frozen={frozen} />
    </div>
  );
};
