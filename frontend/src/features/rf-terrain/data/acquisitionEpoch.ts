import type { SpectrumData } from '../../../shared/types';

// The subset of SpectrumData that changes the physical/mathematical meaning
// of the samples (spec §12): center frequency, span, sample rate, FFT size,
// frequency grid (approximated here by bin count -- comparing every
// frequency value on every frame would be wasteful and span/sampleRate/
// fftSize already capture a grid change), effective RBW, power unit,
// source/device identity, calibration. Gain/detector/averaging are NOT part
// of SpectrumData today, so they cannot be tracked here -- documented
// limitation, not an oversight.
export const computeAcquisitionEpochKey = (frame: SpectrumData): string => [
  frame.centerFrequency,
  frame.span,
  frame.sampleRateHz ?? '',
  frame.fftSize ?? '',
  frame.frequencyArray.length,
  frame.effectiveRbwHz ?? '',
  frame.powerUnit ?? '',
  frame.sourceId ?? '',
  frame.deviceSerial ?? '',
  frame.calibrationId ?? '',
].join('|');

export interface AcquisitionEpochUpdate {
  generation: number;
  changed: boolean;
}

// Stateful tracker (spec §12): the first frame it ever sees opens
// generation 1; every subsequent frame whose key differs from the current
// one bumps the generation. Callers use `changed` to trigger
// RESET/clear on the ring buffer, worker, and (later) every ARST
// accumulator -- never mixing terrains from two different configurations.
export const createAcquisitionEpochTracker = () => {
  let generation = 0;
  let currentKey: string | null = null;

  return {
    update(frame: SpectrumData): AcquisitionEpochUpdate {
      const key = computeAcquisitionEpochKey(frame);
      if (currentKey === null) {
        currentKey = key;
        generation = 1;
        return { generation, changed: true };
      }
      if (key !== currentKey) {
        currentKey = key;
        generation += 1;
        return { generation, changed: true };
      }
      return { generation, changed: false };
    },
    get generation() {
      return generation;
    },
    reset() {
      generation = 0;
      currentKey = null;
    },
  };
};
