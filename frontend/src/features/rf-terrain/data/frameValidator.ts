import type { SpectrumData } from '../../../shared/types';

export type FrameValidationResult =
  | { valid: true; frame: SpectrumData }
  | { valid: false; reason: string };

const isFiniteArray = (values: number[]) => values.every((value) => Number.isFinite(value));

const isMonotonic = (values: number[]) => {
  if (values.length < 2) {
    return true;
  }
  const increasing = values[1] > values[0];
  for (let index = 1; index < values.length; index += 1) {
    const step = values[index] - values[index - 1];
    if (increasing ? step <= 0 : step >= 0) {
      return false;
    }
  }
  return true;
};

// Frame validation (spec §48). Never lets a malformed frame reach the ring
// buffer / worker / renderer -- reject and let the caller count it, never
// throw past this boundary.
export const validateSpectrumFrame = (data: SpectrumData): FrameValidationResult => {
  if (!Number.isFinite(data.timestamp) || data.timestamp <= 0) {
    return { valid: false, reason: 'invalid_timestamp' };
  }
  if (!Number.isFinite(data.centerFrequency)) {
    return { valid: false, reason: 'non_finite_center_frequency' };
  }
  if (!Number.isFinite(data.span) || data.span <= 0) {
    return { valid: false, reason: 'non_positive_span' };
  }
  if (!Array.isArray(data.frequencyArray) || data.frequencyArray.length <= 1) {
    return { valid: false, reason: 'frequency_array_too_short' };
  }
  if (!Array.isArray(data.powerLevels) || data.powerLevels.length !== data.frequencyArray.length) {
    return { valid: false, reason: 'power_levels_length_mismatch' };
  }
  if (!isFiniteArray(data.frequencyArray)) {
    return { valid: false, reason: 'non_finite_frequency_value' };
  }
  if (!isFiniteArray(data.powerLevels)) {
    return { valid: false, reason: 'non_finite_power_value' };
  }
  if (!isMonotonic(data.frequencyArray)) {
    return { valid: false, reason: 'non_monotonic_frequency_array' };
  }

  return { valid: true, frame: data };
};
