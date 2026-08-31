export const dbToLinearPower = (valueDb: number): number => 10 ** (valueDb / 10);

export const linearPowerToDb = (power: number): number => 10 * Math.log10(Math.max(power, 1e-30));

/** Running arithmetic mean of linear power, returned in dB. */
export const updatePowerAverageDb = (previousAverageDb: number, sampleDb: number, previousCount: number): number => {
  const count = Math.max(1, previousCount);
  const meanPower = (dbToLinearPower(previousAverageDb) * count + dbToLinearPower(sampleDb)) / (count + 1);
  return linearPowerToDb(meanPower);
};

/** Running RMS of linear power, sqrt(mean(P^2)), returned in dB. */
export const updateRmsPowerDb = (previousRmsDb: number, sampleDb: number, previousCount: number): number => {
  const count = Math.max(1, previousCount);
  const previousRmsPower = dbToLinearPower(previousRmsDb);
  const samplePower = dbToLinearPower(sampleDb);
  const meanSquaredPower = (previousRmsPower ** 2 * count + samplePower ** 2) / (count + 1);
  return linearPowerToDb(Math.sqrt(meanSquaredPower));
};

export const holdsContainLive = (minHold: number[], live: number[], maxHold: number[], tolerance = 1e-9): boolean => (
  minHold.length === live.length && live.length === maxHold.length && live.every((value, index) => (
    !Number.isFinite(value) || (
      (minHold[index] ?? Number.POSITIVE_INFINITY) <= value + tolerance &&
      value <= (maxHold[index] ?? Number.NEGATIVE_INFINITY) + tolerance
    )
  ))
);

export const densityBucketIndex = (powerDb: number, height: number, minimumDb = -140, maximumDb = 0): number => {
  const normalized = (powerDb - minimumDb) / Math.max(maximumDb - minimumDb, 1e-12);
  return Math.min(height - 1, Math.max(0, Math.floor(normalized * height)));
};

export const updateDensityMatrix = (
  previous: number[], width: number, height: number, powerLevelsDb: number[], decay = 0.995,
): number[] => {
  const matrix = previous.length === width * height
    ? previous.map((value) => value * decay)
    : new Array(width * height).fill(0);
  powerLevelsDb.forEach((powerDb, index) => {
    if (!Number.isFinite(powerDb)) return;
    const frequencyBucket = Math.min(width - 1, Math.floor(index * width / Math.max(powerLevelsDb.length, 1)));
    const powerBucket = densityBucketIndex(powerDb, height);
    matrix[powerBucket * width + frequencyBucket] += 1;
  });
  return matrix;
};

export interface SpectrumGeometryMetadata {
  centerFrequencyHz: number;
  spanHz: number;
  sampleRateHz?: number;
  fftSize?: number;
  binCount: number;
  firstFrequencyHz: number;
  lastFrequencyHz: number;
  binSpacingHz: number;
  effectiveRbwHz?: number;
  sourceId?: string;
  deviceSerial?: string;
  calibrationId?: string;
}

const stableNumber = (value: number | undefined): string => Number.isFinite(value) ? String(value) : 'unknown';

export const spectrumGeometryKey = (geometry: SpectrumGeometryMetadata): string => [
  stableNumber(geometry.centerFrequencyHz), stableNumber(geometry.spanHz),
  stableNumber(geometry.sampleRateHz), stableNumber(geometry.fftSize),
  stableNumber(geometry.binCount), stableNumber(geometry.firstFrequencyHz),
  stableNumber(geometry.lastFrequencyHz), stableNumber(geometry.binSpacingHz),
  stableNumber(geometry.effectiveRbwHz), geometry.sourceId ?? 'unknown',
  geometry.deviceSerial ?? 'unknown', geometry.calibrationId ?? 'uncalibrated',
].join(':');
