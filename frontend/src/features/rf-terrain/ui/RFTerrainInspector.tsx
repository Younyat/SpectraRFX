import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Pin, PinOff } from 'lucide-react';
import type { EpistemicStatus, TerrainInspectorSelection, TerrainObject } from '../model/rfTerrainTypes';
import { EpistemicTag } from './EpistemicTag';
import { HUD_ACCENT_BRIGHT, HUD_BORDER_COLOR, HUD_GLOW_SHADOW, HUD_PANEL_BACKGROUND, hudLabelClass } from './hud/hudTheme';
import { deriveSourceSampleRange, SourceEvidence } from '../offline/sourceEvidence';

interface RFTerrainInspectorProps {
  selection: TerrainInspectorSelection | null;
  objects: TerrainObject[];
  // Segmentation itself always runs -- click-to-select works regardless.
  // This purely controls whether the "Objects (N)" list below is shown.
  showObjectsList: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onUnpin: () => void;
  // Present only while the terrain is showing an OFFLINE reconstruction
  // (spec: FSEI "SOURCE EVIDENCE" -- links a selection back to its exact
  // sample range in the original preserved I/Q). Always null in LIVE, so
  // LIVE's Evidence section renders exactly as before -- unchanged.
  sourceEvidence?: SourceEvidence | null;
}

const fieldRow = (label: string, value: string, status?: EpistemicStatus) => (
  <div className="flex items-center justify-between gap-2 text-xs">
    <span className="app-muted-text">{label}</span>
    <span className="flex items-center gap-1.5">
      <span className="font-mono">{value}</span>
      {status && <EpistemicTag status={status} />}
    </span>
  </div>
);

// A capability that is genuinely absent in this build (no I/Q evidence
// link, no RF Intelligence adapter, no physical-source library) is
// rendered as plain unavailable text, never dressed up with an
// EpistemicTag -- those tags describe the KNOWLEDGE TYPE of a real value,
// not the presence/absence of a whole feature.
const unavailableNotice = (text: string) => (
  <p className="rounded border border-dashed p-2 text-[11px] app-muted-text" style={{ borderColor: HUD_BORDER_COLOR }}>{text}</p>
);

const sectionTitle = (text: string) => (
  <h4 className={`mb-1.5 ${hudLabelClass}`} style={{ color: HUD_ACCENT_BRIGHT }}>{text}</h4>
);

// FSEI (Forensic Spectral Evidence Inspector): a compact cockpit HUD by
// default, expandable into a 7-section dossier. Every field is tagged with
// what kind of knowledge it represents (spec's "zero-tolerance" rule: a
// HYPOTHESIS must never render with the same visual weight as a MEASURED
// or EVIDENCE value) -- real per-bin measurements from the raycaster hit
// are MEASURED, everything computed on top of them (noise floor, excess,
// persistence, occupancy, holds, object metrics) is DERIVED. Sections for
// capabilities that do not exist yet in this build (I/Q evidence linkage,
// an RF Intelligence adapter, a physical-source signature library) render
// an honest unavailable notice instead of a fabricated value.
export const RFTerrainInspector: React.FC<RFTerrainInspectorProps> = ({ selection, objects, showObjectsList, collapsed, onToggleCollapsed, onUnpin, sourceEvidence = null }) => {
  const [expanded, setExpanded] = useState(false);
  const matchedObject = selection?.objectId ? objects.find((object) => object.id === selection.objectId) ?? null : null;

  return (
    <div className="pointer-events-none absolute inset-y-0 right-0 z-20 flex items-stretch">
      <button
        onClick={onToggleCollapsed}
        title={collapsed ? 'Show inspector' : 'Hide inspector'}
        className="pointer-events-auto my-auto flex h-10 w-6 items-center justify-center rounded-l-sm border border-r-0 backdrop-blur hover:brightness-125"
        style={{ borderColor: HUD_BORDER_COLOR, background: HUD_PANEL_BACKGROUND }}
      >
        {collapsed ? <ChevronLeft className="h-4 w-4" style={{ color: HUD_ACCENT_BRIGHT }} /> : <ChevronRight className="h-4 w-4" style={{ color: HUD_ACCENT_BRIGHT }} />}
      </button>
      <div
        className="pointer-events-auto flex h-full w-80 flex-shrink-0 flex-col gap-3 overflow-y-auto border-l p-3 backdrop-blur-md transition-transform duration-200"
        style={{
          borderColor: HUD_BORDER_COLOR,
          background: HUD_PANEL_BACKGROUND,
          boxShadow: HUD_GLOW_SHADOW,
          transform: collapsed ? 'translateX(100%)' : 'translateX(0)',
        }}
      >
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className={hudLabelClass} style={{ color: HUD_ACCENT_BRIGHT }}>Object Details</h3>
            {selection && (
              <button
                onClick={onUnpin}
                title={selection.pinned ? 'Unpin selection' : 'Pin selection'}
                className="flex items-center gap-1 rounded-sm border px-2 py-0.5 text-[10px]"
                style={{ borderColor: selection.pinned ? '#d4af37' : HUD_BORDER_COLOR, color: selection.pinned ? '#d4af37' : undefined }}
              >
                {selection.pinned ? <Pin className="h-3 w-3" /> : <PinOff className="h-3 w-3" />}
                {selection.pinned ? 'Pinned' : 'Unpinned'}
              </button>
            )}
          </div>

          {!selection && <p className="text-xs app-muted-text">Click on the terrain to inspect a point or object.</p>}

          {selection && (
            <div className="space-y-2 rounded-lg border p-2" style={{ borderColor: selection.outOfView ? '#f59e0b' : HUD_BORDER_COLOR }}>
              {selection.outOfView && (
                <div className="rounded border border-amber-500/60 bg-amber-500/10 p-1.5 text-[10px] text-amber-300">
                  OUT OF VIEW -- the selected row aged out of the bounded history window. The values shown are the last real ones known, not a live reading.
                </div>
              )}

              <div className="flex items-center gap-2">
                <span className="rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide" style={{ borderColor: HUD_BORDER_COLOR }}>
                  {selection.kind === 'TERRAIN_OBJECT' ? 'Terrain object' : 'Point'}
                </span>
                {matchedObject?.origin === 'AI_DETECTION' ? (
                  <span className="rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300" style={{ borderColor: '#f97316' }}>
                    AI detection
                  </span>
                ) : matchedObject && (
                  <span className="rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wide" style={{ borderColor: HUD_BORDER_COLOR }}>
                    {matchedObject.morphology}
                  </span>
                )}
              </div>

              {matchedObject?.aiDetection && (
                <div className="rounded border p-1.5" style={{ borderColor: '#f97316' }}>
                  {fieldRow('Model', matchedObject.aiDetection.modelName, 'EVIDENCE')}
                  {fieldRow('Result', matchedObject.aiDetection.summary, 'HYPOTHESIS')}
                  {matchedObject.aiDetection.classDescription && (
                    <p className="mt-1 text-[10px] app-muted-text">
                      {matchedObject.aiDetection.classDescription.text}
                      <span className="ml-1 text-[9px] italic">
                        ({matchedObject.aiDetection.classDescription.source === 'MODEL_OVERRIDE' ? 'model-specific description' : 'standard term reference'})
                      </span>
                    </p>
                  )}
                  {!matchedObject.aiDetection.classDescription && matchedObject.aiDetection.predictedClass && (
                    <p className="mt-1 text-[10px] text-amber-300">
                      No description set for "{matchedObject.aiDetection.predictedClass}" -- add one via the model's overrides in the FSEI -- AI panel.
                    </p>
                  )}
                  {fieldRow('Latency', matchedObject.aiDetection.totalLatencyMs === null ? 'unknown' : `${matchedObject.aiDetection.totalLatencyMs.toFixed(0)} ms`, 'MEASURED')}
                  {!matchedObject.aiDetection.bandwidthIsKnown && (
                    <p className="mt-1 text-[10px] app-muted-text">
                      Frequency box width is an approximate marker, not a measured/declared signal bandwidth -- this model has no `expected_signal_bandwidth_hz` override set.
                    </p>
                  )}
                </div>
              )}

              {fieldRow('Frequency', `${(selection.frequencyHz / 1e6).toFixed(4)} MHz`, 'MEASURED')}
              {fieldRow('Time', new Date(selection.timestamp).toLocaleTimeString(), 'MEASURED')}
              {fieldRow('Raw power', `${selection.rawPowerDb.toFixed(1)} ${selection.powerUnit}`, 'MEASURED')}
              {fieldRow('Estimated floor', `${selection.noiseFloorDb.toFixed(1)} ${selection.powerUnit}`, 'DERIVED')}
              {fieldRow('Excess over noise', `${selection.excessDb.toFixed(1)} dB`, 'DERIVED')}
              {fieldRow('Persistence', `${(selection.persistence * 100).toFixed(0)}%`, 'DERIVED')}
              {fieldRow('Occupancy', `${(selection.occupancy * 100).toFixed(0)}%`, 'DERIVED')}
              {fieldRow('Associated object', matchedObject ? matchedObject.trackId : '—')}

              <button
                onClick={() => setExpanded((prev) => !prev)}
                className="flex w-full items-center justify-center gap-1 rounded border py-1 text-[10px] uppercase tracking-wide app-muted-text hover:bg-white/5"
                style={{ borderColor: HUD_BORDER_COLOR }}
              >
                {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {expanded ? 'Hide dossier' : 'Full forensic dossier'}
              </button>

              {expanded && (
                <div className="space-y-3 border-t pt-2" style={{ borderColor: HUD_BORDER_COLOR }}>
                  <div>
                    {sectionTitle('1. Measurement')}
                    {fieldRow('Exact frequency', `${selection.frequencyHz.toFixed(0)} Hz`, 'MEASURED')}
                    {fieldRow('Timestamp', new Date(selection.timestamp).toISOString(), 'MEASURED')}
                    {fieldRow('Raw power', `${selection.rawPowerDb.toFixed(2)} ${selection.powerUnit}`, 'MEASURED')}
                    {fieldRow('Acquisition generation', String(selection.generation), 'MEASURED')}
                  </div>

                  <div>
                    {sectionTitle('2. Terrain derivation')}
                    {fieldRow('Noise floor (adaptive P20)', `${selection.noiseFloorDb.toFixed(2)} ${selection.powerUnit}`, 'DERIVED')}
                    {fieldRow('Excess over noise', `${selection.excessDb.toFixed(2)} dB`, 'DERIVED')}
                    {fieldRow('Persistence (θ=6dB, τ=2s)', `${(selection.persistence * 100).toFixed(1)}%`, 'DERIVED')}
                    {fieldRow('Occupancy (τ=20s)', `${(selection.occupancy * 100).toFixed(1)}%`, 'DERIVED')}
                    {fieldRow('Max Hold', `${selection.maxHoldDb.toFixed(2)} ${selection.powerUnit}`, 'DERIVED')}
                    {fieldRow('Min Hold', `${selection.minHoldDb.toFixed(2)} ${selection.powerUnit}`, 'DERIVED')}
                    {fieldRow('Average (linear EWMA)', `${selection.averageDb.toFixed(2)} ${selection.powerUnit}`, 'DERIVED')}
                    {fieldRow('EWMA (dB domain)', `${selection.ewmaDb.toFixed(2)} ${selection.powerUnit}`, 'DERIVED')}
                  </div>

                  <div>
                    {sectionTitle('3. Object context')}
                    {matchedObject?.origin === 'AI_DETECTION' ? (
                      <>
                        {fieldRow('ID', matchedObject.trackId, 'EVIDENCE')}
                        {fieldRow('Center frequency', `${(matchedObject.centerFrequencyHz / 1e6).toFixed(4)} MHz`, 'EVIDENCE')}
                        {fieldRow('Analyzed bandwidth', `${(matchedObject.bandwidthHz / 1e3).toFixed(1)} kHz`, 'EVIDENCE')}
                        {unavailableNotice('No real segmentation geometry (peak/mean excess, TVI, cell count, ridge slope) exists for an AI-injected region -- it is a bounding box around a model result, not a measured terrain shape. See section 5 for the real model output.')}
                      </>
                    ) : matchedObject ? (
                      <>
                        {fieldRow('Track ID', matchedObject.trackId, 'DERIVED')}
                        {fieldRow('Morphology', matchedObject.morphology, 'DERIVED')}
                        {fieldRow('State', matchedObject.active ? 'ACTIVE' : 'ENDED', 'DERIVED')}
                        {fieldRow('Bandwidth', `${(matchedObject.bandwidthHz / 1e3).toFixed(1)} kHz`, 'DERIVED')}
                        {fieldRow('Duration', `${matchedObject.durationSeconds.toFixed(2)} s`, 'DERIVED')}
                        {fieldRow('Peak excess', `${matchedObject.peakExcessDb.toFixed(1)} dB`, 'DERIVED')}
                        {fieldRow('Mean excess', `${matchedObject.meanExcessDb.toFixed(1)} dB`, 'DERIVED')}
                        {fieldRow('Frequency centroid', `${(matchedObject.frequencyCentroidHz / 1e6).toFixed(4)} MHz`, 'DERIVED')}
                        {fieldRow('Ridge slope', matchedObject.ridgeSlopeHzPerSecond === null ? '—' : `${(matchedObject.ridgeSlopeHzPerSecond / 1e3).toFixed(1)} kHz/s`, 'DERIVED')}
                        {fieldRow('Terrain Volume Index (TVI)', matchedObject.terrainVolumeIndex.toFixed(2), 'DERIVED')}
                        {fieldRow('Cells', String(matchedObject.cellCount), 'DERIVED')}
                      </>
                    ) : unavailableNotice('Not applicable: this is a point selection, not part of a segmented terrain object.')}
                  </div>

                  <div>
                    {sectionTitle('4. Evidence -- Source')}
                    {sourceEvidence ? (
                      (() => {
                        const range = deriveSourceSampleRange(selection.timestamp, sourceEvidence);
                        return (
                          <>
                            {fieldRow('Capture ID', sourceEvidence.captureId, 'EVIDENCE')}
                            {fieldRow('Data SHA-256', `${sourceEvidence.dataSha256.slice(0, 16)}…`, 'EVIDENCE')}
                            {fieldRow('Sample rate', `${(sourceEvidence.sampleRateSps / 1e6).toFixed(3)} Msps`, 'EVIDENCE')}
                            {fieldRow('Sample range', `[${range.startSampleIndex.toLocaleString()}, ${range.endSampleIndex.toLocaleString()}]`, 'DERIVED')}
                            {fieldRow('Time range in capture', `${range.startTimeSeconds.toFixed(6)}s – ${range.endTimeSeconds.toFixed(6)}s`, 'DERIVED')}
                            <p className="mt-1 text-[10px] app-muted-text">
                              Exact link to the preserved I/Q window this row was reconstructed from -- not an inference.
                            </p>
                          </>
                        );
                      })()
                    ) : (
                      unavailableNotice('I/Q capture linkage: UNAVAILABLE -- this is a LIVE reading; no raw capture is preserved or linked to it.')
                    )}
                  </div>

                  <div>
                    {sectionTitle('5. Intelligent hypothesis')}
                    {matchedObject?.aiDetection ? (
                      <>
                        {fieldRow('Model', matchedObject.aiDetection.modelName, 'EVIDENCE')}
                        {fieldRow('Model ID', matchedObject.aiDetection.modelId, 'EVIDENCE')}
                        {fieldRow('Result', matchedObject.aiDetection.summary, 'HYPOTHESIS')}
                        {fieldRow('Detected at', new Date(matchedObject.aiDetection.detectedAtUtc).toLocaleString(), 'MEASURED')}
                        {fieldRow('End-to-end latency', matchedObject.aiDetection.totalLatencyMs === null ? 'unknown' : `${matchedObject.aiDetection.totalLatencyMs.toFixed(0)} ms`, 'MEASURED')}
                        {matchedObject.aiDetection.predictedClass && (
                          fieldRow(
                            'Class meaning',
                            matchedObject.aiDetection.classDescription?.text ?? 'no description set',
                            matchedObject.aiDetection.classDescription?.source === 'MODEL_OVERRIDE' ? 'EVIDENCE' : matchedObject.aiDetection.classDescription ? 'DERIVED' : undefined,
                          )
                        )}
                        <p className="mt-1 text-[10px] app-muted-text">
                          A prediction from this imported model's own training -- never a confirmed device/protocol identification. See the FSEI -- AI panel for the model's full manifest and compatibility check.
                        </p>
                      </>
                    ) : unavailableNotice('Device/protocol identification: UNAVAILABLE -- no RF Intelligence adapter is connected in this build.')}
                  </div>

                  <div>
                    {sectionTitle('6. Physical-source comparison')}
                    {unavailableNotice('NOT_AVAILABLE_FOR_THIS_OBJECT -- no physical-source signature library exists to compare against.')}
                  </div>

                  <div>
                    {sectionTitle('7. Quality / uncertainty')}
                    {fieldRow('Power unit', selection.powerUnit, 'MEASURED')}
                    {fieldRow('Calibration', selection.calibrationId ?? 'none', 'MEASURED')}
                    {fieldRow('Frequency bins (grid)', '512 (resampled to a fixed grid)', 'DERIVED')}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {showObjectsList && (
          <div>
            <h3 className={`mb-2 ${hudLabelClass}`} style={{ color: HUD_ACCENT_BRIGHT }}>Objects ({objects.length})</h3>
            <div className="space-y-2">
              {objects.map((object) => (
                <div key={object.id} className="rounded-lg border p-2 text-[11px]" style={{ borderColor: object.origin === 'AI_DETECTION' ? '#f97316' : object.active ? '#4ade80' : HUD_BORDER_COLOR }}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="font-mono text-[10px] app-muted-text">{object.trackId}</span>
                    <span
                      className="rounded border px-1 py-0.5 text-[9px] uppercase tracking-wide"
                      style={{ borderColor: object.origin === 'AI_DETECTION' ? '#f97316' : HUD_BORDER_COLOR, color: object.origin === 'AI_DETECTION' ? '#fdba74' : undefined }}
                    >
                      {object.origin === 'AI_DETECTION' ? 'AI detection' : object.morphology}
                    </span>
                  </div>
                  {object.origin === 'AI_DETECTION' && object.aiDetection ? (
                    <>
                      {fieldRow('Model', object.aiDetection.modelName)}
                      {fieldRow('Result', object.aiDetection.summary)}
                      {fieldRow('Frequency', `${(object.centerFrequencyHz / 1e6).toFixed(4)} MHz`)}
                      {fieldRow('Latency', object.aiDetection.totalLatencyMs === null ? 'unknown' : `${object.aiDetection.totalLatencyMs.toFixed(0)} ms`)}
                    </>
                  ) : (
                    <>
                      {fieldRow('BW', `${(object.bandwidthHz / 1e3).toFixed(1)} kHz`)}
                      {fieldRow('Duration', `${object.durationSeconds.toFixed(2)} s`)}
                      {fieldRow('Peak excess', `${object.peakExcessDb.toFixed(1)} dB`)}
                      {fieldRow('Slope', object.ridgeSlopeHzPerSecond === null ? '—' : `${(object.ridgeSlopeHzPerSecond / 1e3).toFixed(1)} kHz/s`)}
                      {fieldRow('TVI', object.terrainVolumeIndex.toFixed(2))}
                      {fieldRow('State', object.active ? 'ACTIVE' : 'ENDED')}
                    </>
                  )}
                </div>
              ))}
              {objects.length === 0 && <p className="text-xs app-muted-text">No objects detected yet.</p>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
