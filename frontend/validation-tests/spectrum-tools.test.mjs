import test from 'node:test';
import assert from 'node:assert/strict';
import {
  dbToLinearPower,
  holdsContainLive,
  linearPowerToDb,
  spectrumGeometryKey,
  updatePowerAverageDb,
  updateRmsPowerDb,
  updateDensityMatrix,
} from '../.validation-build/spectrumMath.js';
import { SPECTRUM_SERIES_IDS } from '../.validation-build/seriesIdentity.js';

const closeTo = (actual, expected, tolerance = 1e-9) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
};

test('same-frame invariant Min Hold <= Live <= Max Hold', () => {
  const frames = [[-70, -50, -90], [-60, -80, -40], [-75, -45, -65]];
  let minHold;
  let maxHold;
  for (const live of frames) {
    minHold = minHold ? live.map((value, index) => Math.min(minHold[index], value)) : [...live];
    maxHold = maxHold ? live.map((value, index) => Math.max(maxHold[index], value)) : [...live];
    assert.equal(holdsContainLive(minHold, live, maxHold), true);
  }
  assert.equal(holdsContainLive([-80], [-30], [-40]), false);
});

test('Power Average and RMS use independent linear-power formulas', () => {
  const firstDb = -40;
  const secondDb = -80;
  const p1 = dbToLinearPower(firstDb);
  const p2 = dbToLinearPower(secondDb);
  const expectedAverageDb = linearPowerToDb((p1 + p2) / 2);
  const expectedRmsDb = linearPowerToDb(Math.sqrt((p1 ** 2 + p2 ** 2) / 2));
  const averageDb = updatePowerAverageDb(firstDb, secondDb, 1);
  const rmsDb = updateRmsPowerDb(firstDb, secondDb, 1);
  closeTo(averageDb, expectedAverageDb);
  closeTo(rmsDb, expectedRmsDb);
  closeTo(averageDb, -43.00986568387118);
  closeTo(rmsDb, -41.50514995660518);
  assert.notEqual(averageDb, rmsDb);
  for (const field of ['processor', 'buffer', 'result', 'graphic']) {
    assert.notEqual(SPECTRUM_SERIES_IDS.powerAverage[field], SPECTRUM_SERIES_IDS.rmsPower[field], field);
  }
});

test('Density is a two-dimensional frequency-power matrix with separated bands', () => {
  const width = 1;
  const height = 128;
  let matrix = new Array(width * height).fill(0);
  for (let frame = 0; frame < 100; frame += 1) {
    const powerDb = frame % 2 === 0 ? -45 : -70;
    matrix = updateDensityMatrix(matrix, width, height, [powerDb]);
  }
  const occupiedRows = matrix.map((value, row) => ({ value, row })).filter(({ value }) => value > 0);
  assert.equal(occupiedRows.length, 2);
  assert.ok(occupiedRows.every(({ value }) => value > 0));
  assert.ok(Math.abs(occupiedRows[0].value - occupiedRows[1].value) < 1);
  assert.ok(occupiedRows[1].row - occupiedRows[0].row > 1);
  for (let row = occupiedRows[0].row + 1; row < occupiedRows[1].row; row += 1) assert.equal(matrix[row], 0);
});

test('geometry key changes for every acquisition-compatibility field only', () => {
  const base = { centerFrequencyHz: 100e6, spanHz: 2e6, sampleRateHz: 2e6, fftSize: 2048, binCount: 2048, firstFrequencyHz: 99e6, lastFrequencyHz: 100999023.4375, binSpacingHz: 976.5625, effectiveRbwHz: 1464.84375, sourceId: 'uhd', deviceSerial: 'ABC', calibrationId: 'uncalibrated' };
  const baseKey = spectrumGeometryKey(base);
  const changes = { centerFrequencyHz: 101e6, spanHz: 1e6, sampleRateHz: 1e6, fftSize: 4096, binCount: 4096, firstFrequencyHz: 99.5e6, lastFrequencyHz: 101e6, binSpacingHz: 488.28125, effectiveRbwHz: 732.421875, sourceId: 'replay', deviceSerial: 'XYZ', calibrationId: 'cal-2' };
  for (const [field, value] of Object.entries(changes)) assert.notEqual(spectrumGeometryKey({ ...base, [field]: value }), baseKey, field);
});
