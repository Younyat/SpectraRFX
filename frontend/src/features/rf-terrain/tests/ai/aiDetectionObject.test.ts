import { describe, expect, it } from 'vitest';
import { AI_DETECTION_TIME_WINDOW_SECONDS, buildAiDetectionTerrainObject, pruneExpiredAiDetectionObjects } from '../../ai/aiDetectionObject';
import type { AiLiveDetection, TerrainObject } from '../../model/rfTerrainTypes';

const detection = (overrides: Partial<AiLiveDetection> = {}): AiLiveDetection => ({
  id: 'AI-DETECTION-1',
  modelId: 'AI-MODEL-1',
  modelName: 'Toy Model',
  detectedAtUtc: '2026-01-01T00:00:10.000Z',
  centerFrequencyHz: 2_440_000_000,
  bandwidthHz: 2_000_000,
  summary: 'QPSK (probability=0.870)',
  totalLatencyMs: 92,
  ...overrides,
});

describe('buildAiDetectionTerrainObject', () => {
  it('produces a real, selectable bounding box around the detection frequency/time', () => {
    const object = buildAiDetectionTerrainObject(detection());
    const detectedAtSeconds = new Date('2026-01-01T00:00:10.000Z').getTime() / 1000;

    expect(object.id).toBe('AI-DETECTION-1');
    expect(object.centerFrequencyHz).toBe(2_440_000_000);
    expect(object.startFrequencyHz).toBe(2_440_000_000 - 1_000_000);
    expect(object.stopFrequencyHz).toBe(2_440_000_000 + 1_000_000);
    expect(object.startTimeSeconds).toBeCloseTo(detectedAtSeconds - AI_DETECTION_TIME_WINDOW_SECONDS);
    expect(object.endTimeSeconds).toBeCloseTo(detectedAtSeconds + AI_DETECTION_TIME_WINDOW_SECONDS);
  });

  it('is tagged with origin AI_DETECTION and carries the real model info', () => {
    const object = buildAiDetectionTerrainObject(detection());
    expect(object.origin).toBe('AI_DETECTION');
    expect(object.aiDetection).toEqual({
      modelId: 'AI-MODEL-1',
      modelName: 'Toy Model',
      summary: 'QPSK (probability=0.870)',
      detectedAtUtc: '2026-01-01T00:00:10.000Z',
      totalLatencyMs: 92,
    });
  });

  it('never fabricates real segmentation metrics -- geometric fields are honestly zeroed/null', () => {
    const object = buildAiDetectionTerrainObject(detection());
    expect(object.peakExcessDb).toBe(0);
    expect(object.meanExcessDb).toBe(0);
    expect(object.terrainVolumeIndex).toBe(0);
    expect(object.cellCount).toBe(0);
    expect(object.ridgeSlopeHzPerSecond).toBeNull();
  });

  it('never divides by zero for a zero-bandwidth detection', () => {
    const object = buildAiDetectionTerrainObject(detection({ bandwidthHz: 0 }));
    expect(object.stopFrequencyHz).toBeGreaterThan(object.startFrequencyHz);
  });
});

describe('pruneExpiredAiDetectionObjects', () => {
  const segmentationObject: TerrainObject = {
    id: 'SEG-1', trackId: 'SEG-1', startTimeSeconds: 0, endTimeSeconds: 1_000_000_000, durationSeconds: 1,
    startFrequencyHz: 0, stopFrequencyHz: 1, centerFrequencyHz: 0.5, bandwidthHz: 1,
    peakExcessDb: 5, meanExcessDb: 3, frequencyCentroidHz: 0.5, temporalCentroidSeconds: 0,
    terrainVolumeIndex: 1, ridgeSlopeHzPerSecond: null, cellCount: 10, morphology: 'RIDGE', active: true,
  };

  it('keeps real segmentation objects regardless of the AI time window', () => {
    const result = pruneExpiredAiDetectionObjects([segmentationObject], 999_999_999);
    expect(result).toEqual([segmentationObject]);
  });

  it('drops an AI detection object whose window has fully elapsed', () => {
    const object = buildAiDetectionTerrainObject(detection());
    const farFuture = object.endTimeSeconds + 100;
    expect(pruneExpiredAiDetectionObjects([object], farFuture)).toEqual([]);
  });

  it('keeps an AI detection object still inside its window', () => {
    const object = buildAiDetectionTerrainObject(detection());
    const stillWithinWindow = object.startTimeSeconds + 1;
    expect(pruneExpiredAiDetectionObjects([object], stillWithinWindow)).toEqual([object]);
  });
});
