import NoDataNotice from '../NoDataNotice';

export interface NonInferiorityDatum {
  label: string;
  /** NonInferiorityResult.mean_difference (new - reference). */
  meanDifference: number;
  /** NonInferiorityResult.ci_low -- one-sided lower bound only; the test
   * has no upper bound by construction, so this chart never draws one. */
  ciLow: number;
  /** The pre-registered, always-positive tolerance -- the decision
   * boundary drawn is at x = -margin, exactly non_inferiority_test()'s own
   * rule (non-inferior iff ci_low > -margin). */
  margin: number;
  /** Read verbatim from NonInferiorityResult.non_inferior -- never
   * re-derived from ciLow/margin in the frontend. */
  nonInferior: boolean;
}

const WIDTH = 520;
const ROW_HEIGHT = 44;
const PAD = { top: 24, right: 24, bottom: 32, left: 180 };

/** RQ4 non-inferiority forest plot -- point estimate, one-sided lower CI
 * whisker, and the frozen margin's decision boundary, exactly the three
 * quantities non_inferiority_test() itself produces. Dependency-free SVG
 * (same rationale as PairedPrePostChart: no off-the-shelf recharts
 * category axis renders reliably here) -- pure renderer, never computes
 * non-inferiority itself. */
export default function NonInferiorityChart({
  data,
  noDataReason,
}: {
  data: NonInferiorityDatum[] | null | undefined;
  noDataReason: string;
}) {
  if (!data || data.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const height = PAD.top + PAD.bottom + data.length * ROW_HEIGHT;
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const boundary = -data[0].margin;
  const allValues = data.flatMap((d) => [d.meanDifference, d.ciLow, boundary, 0]);
  const minValue = Math.min(...allValues);
  const maxValue = Math.max(...allValues);
  const span = maxValue - minValue || 1;
  const padSpan = span * 0.15;
  const domainMin = minValue - padSpan;
  const domainMax = maxValue + padSpan;
  const xFor = (v: number) => PAD.left + plotWidth * ((v - domainMin) / (domainMax - domainMin));

  return (
    <div className="overflow-x-auto">
      <svg role="img" aria-label="Non-inferiority forest plot" width={WIDTH} height={height} viewBox={`0 0 ${WIDTH} ${height}`}>
        <line x1={xFor(0)} y1={PAD.top - 8} x2={xFor(0)} y2={height - PAD.bottom + 4} stroke="#475569" strokeWidth={1} />
        <line x1={xFor(boundary)} y1={PAD.top - 8} x2={xFor(boundary)} y2={height - PAD.bottom + 4} stroke="#f87171" strokeDasharray="4 4" strokeWidth={1} />
        <text x={xFor(boundary)} y={PAD.top - 10} fill="#f87171" fontSize={10} textAnchor="middle">frontera (-margin={boundary.toFixed(3)})</text>

        {data.map((d, index) => {
          const y = PAD.top + index * ROW_HEIGHT + ROW_HEIGHT / 2;
          return (
            <g key={d.label} data-testid="non-inferiority-row">
              <text x={PAD.left - 12} y={y} fill="#cbd5e1" fontSize={11} textAnchor="end" dominantBaseline="middle">{d.label}</text>
              <line x1={xFor(d.ciLow)} y1={y} x2={xFor(d.meanDifference)} y2={y} stroke="#e2e8f0" strokeWidth={1.5} />
              <line x1={xFor(d.ciLow)} y1={y - 5} x2={xFor(d.ciLow)} y2={y + 5} stroke="#e2e8f0" strokeWidth={1.5} />
              <circle cx={xFor(d.meanDifference)} cy={y} r={4} fill={d.nonInferior ? '#34d399' : '#f87171'} />
              <text x={xFor(d.meanDifference)} y={y - 12} fill="#94a3b8" fontSize={10} textAnchor="middle">
                {d.meanDifference.toFixed(3)} [{d.ciLow.toFixed(3)}, +inf)
              </text>
            </g>
          );
        })}

        <line x1={PAD.left} y1={height - PAD.bottom} x2={WIDTH - PAD.right} y2={height - PAD.bottom} stroke="#334155" />
        <text x={PAD.left + plotWidth / 2} y={height - 8} fill="#94a3b8" fontSize={11} textAnchor="middle">diferencia (nuevo - referencia)</text>
      </svg>
    </div>
  );
}
