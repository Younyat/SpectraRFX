# Spectrum Tools Critical Validation

This document freezes the validated behavior of the existing multi-tool
interface. It does not introduce additional techniques or redesign the UI.

## Power unit and effective RBW

The live UHD worker computes a Hann-windowed FFT as:

```text
S[k] = FFT{x[n] w[n]}
A[k] = |S[k]| / sum(w[n])
X_dBFS[k] = 20 log10(A[k] + 1e-12)
```

There is no absolute receiver-chain calibration, antenna-factor correction, or
traceable power reference in this path. Therefore the vertical unit is
**dBFS**, not dBm. A configured display offset is shown explicitly and does not
turn dBFS into calibrated dBm.

For the Hann window, the worker reports:

```text
effective_RBW_hz = sample_rate_hz * 1.5 / fft_size
```

Both the power unit and effective RBW are carried in each frame and displayed
in Live Monitor.

## Hold invariant

For one immutable input frame `X_k` and one compatible frequency grid:

```text
Min_k[i] = min(Min_{k-1}[i], X_k[i])
Max_k[i] = max(Max_{k-1}[i], X_k[i])
```

The automated test checks after every synthetic frame:

```text
Min Hold[i] <= Live[i] <= Max Hold[i]
```

Production also performs this invariant check whenever Min Hold and Max Hold
are active together.

## Power Average

Input dB values are converted to linear power:

```text
P_k[i] = 10 ** (X_k_dB[i] / 10)
```

The arithmetic power mean and displayed result are:

```text
A_N[i] = (1/N) sum(P_k[i])
Average_dB[i] = 10 log10(A_N[i])
```

The running implementation is algebraically equivalent:

```text
A_{N+1} = (N A_N + P_{N+1}) / (N + 1)
```

## RMS Power over FFT frames

RMS Power over FFT frames is calculated over linear power, independently of
Power Average. It is not True IQ RMS: this metric is not calculated directly
from time-domain IQ samples.

```text
R_N[i] = sqrt((1/N) sum(P_k[i] ** 2))
RMS_dB[i] = 10 log10(R_N[i])
```

The running implementation is:

```text
R_{N+1} = sqrt((N R_N ** 2 + P_{N+1} ** 2) / (N + 1))
```

Power Average and RMS use distinct:

- processor functions: `updatePowerAverageDb` and `updateRmsPowerDb`;
- buffer keys: `power_average` and `rms_power`;
- result/tool IDs: `power_average` and `rms_power`;
- graphical IDs: `power-average` and `rms-power`.

## Synthetic −40/−80 dB result

For equal observations at `−40 dB` and `−80 dB`:

```text
P1 = 10 ** (-40/10) = 1e-4
P2 = 10 ** (-80/10) = 1e-8

Power Average = 10 log10((P1 + P2) / 2)
              = -43.00986568387118 dB

RMS Power over FFT frames = 10 log10(sqrt((P1^2 + P2^2) / 2))
                          = -41.50514995660518 dB
```

These values are asserted against the exact production functions.

## Density/Persistence matrix

Density is stored as a bounded row-major matrix:

```text
matrix[power_bucket * frequency_width + frequency_bucket]
```

The synthetic test sends 100 frames to one frequency bin:

- 50 frames at `−45 dB`;
- 50 frames at `−70 dB`.

The result has exactly two occupied power rows. Each receives 50 updates (the
stored weights are slightly lower because production applies bounded temporal
decay). All rows between the two bands remain zero, proving this is a
frequency–power matrix rather than a continuous filled area.

## Geometry reset policy

The statistical generation key includes:

- center frequency;
- span;
- sample rate;
- FFT size;
- bin count;
- first and last bin frequencies;
- bin spacing;
- effective RBW;
- source ID;
- device serial;
- calibration ID.

A change in any field creates a new generation and clears incompatible
statistical buffers and sample counts. Visibility and color are deliberately
absent from the key.

## Hide, reset, and disable

- **Hide** changes only `visible`; the processor remains active and buffers keep
  receiving frames.
- **Reset** clears only the selected tool's buffers and sample count while the
  tool remains active.
- **Disable** invokes the selected tool reset, marks it inactive and invisible,
  and releases its accumulated state.

Changing a color updates presentation preferences only. It does not clear a
processor or alter the geometry key.

## Automated validation

Run:

```powershell
cd frontend
npm run test:spectrum-tools
```

The suite covers hold ordering, exact Average/RMS results and independent IDs,
two-band Density behavior, and every acquisition-geometry field.

## Regression evidence

The critical mathematical and implementation validation is complete. The
validated scope includes dBFS semantics, effective RBW, hold ordering, Power
Average, RMS Power over FFT frames, Density, geometry resets, and exact
chronological pre-trigger retention. `noiseFloorOffset` is a display offset
only and is not a receiver calibration.

Validated in this change:

- frontend TypeScript/Vite production build;
- UHD discovery and B200 probe;
- real UHD/GNU Radio spectrum worker frame;
- frame unit `dBFS`, device serial, FFT size, sample rate, and effective RBW;
- Python compilation of the spectrum worker;
- circular pre-trigger retention and adaptive energy trigger.

The pre-trigger validation found and corrected a block-boundary truncation:
the circular buffer now retains the exact newest `max_samples`, including a
partial oldest block.

## Pending before final close or merge

The following operational validation remains pending and is not claimed as
complete:

1. Repair the backend Python environment and run the complete pytest suite.
2. Run a minimal browser E2E check of marker, zoom, pan, menu, and legend.
3. Run a controlled IQ capture with declared frequency, sample rate/bandwidth,
   gain, duration or trigger policy, known transmitter/source, output location,
   retention decision, and cleanup policy.

No UI redesign or change to the validated algorithms is required for these
remaining checks.
