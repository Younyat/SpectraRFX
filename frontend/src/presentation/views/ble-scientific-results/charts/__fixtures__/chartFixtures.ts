// Explicitly synthetic fixtures for chart-primitive component tests only.
// Imported ONLY by *.test.tsx files in this folder -- never by a tab
// component or any production code path.
import { BarWithCiDatum } from '../BarWithCiChart';
import { NonInferiorityDatum } from '../NonInferiorityChart';
import { PairedPrePostDatum } from '../PairedPrePostChart';
import { RiskCoveragePoint } from '../RiskCoverageChart';
import { ScatterDatum } from '../ScatterChart';

export const BAR_WITH_CI_SYNTHETIC_FIXTURE: BarWithCiDatum[] = [
  { category: 'capture-dependent', value: 0.91, ciLow: 0.85, ciHigh: 0.95 },
  { category: 'capture-disjoint', value: 0.62, ciLow: 0.5, ciHigh: 0.7 },
  { category: 'future', value: 0.58, ciLow: null, ciHigh: null },
];

export const PAIRED_PRE_POST_SYNTHETIC_FIXTURE: PairedPrePostDatum[] = [
  { unitId: 'UNIT-A', pre: 0.3, post: 0.6 },
  { unitId: 'UNIT-B', pre: 0.4, post: 0.35 },
];

export const CONFUSION_MATRIX_SYNTHETIC_FIXTURE: Record<string, Record<string, number>> = {
  A: { A: 8, B: 2 },
  B: { A: 1, B: 9 },
};

export const RISK_COVERAGE_SYNTHETIC_FIXTURE: RiskCoveragePoint[] = [
  { coverage: 1.0, risk: 0.2 },
  { coverage: 0.8, risk: 0.1 },
  { coverage: 0.5, risk: 0.02 },
];

export const ECDF_SYNTHETIC_FIXTURE: number[] = [12, 15, 14, 20, 18, 30, 22, 16];

export const HISTOGRAM_SYNTHETIC_FIXTURE: number[] = [0.01, 0.02, 0.015, -0.01, 0.03, 0.0, -0.02, 0.04, 0.01, 0.02];

export const NON_INFERIORITY_SYNTHETIC_FIXTURE: NonInferiorityDatum[] = [
  { label: 'FULL_BURST vs ADVA_EXCLUDED', meanDifference: -0.02, ciLow: -0.06, margin: 0.1, nonInferior: true },
];

export const SCATTER_SYNTHETIC_FIXTURE: ScatterDatum[] = [
  { label: 'engineered_rf', x: 4.2, y: 0.91 },
  { label: 'raw_iq', x: 12.5, y: 0.95 },
];
