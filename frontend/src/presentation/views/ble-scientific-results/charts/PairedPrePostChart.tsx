import NoDataNotice from '../NoDataNotice';

export interface PairedPrePostDatum {
  unitId: string;
  pre: number;
  post: number;
}

const WIDTH = 480;
const HEIGHT = 260;
const PAD = { top: 16, right: 90, bottom: 28, left: 40 };

/** RQ3 paired PRE->POST per physical unit, one arm (RESET or CONTROL) per
 * instance -- render two instances side by side for both arms. No
 * off-the-shelf recharts primitive draws "one line per entity between two
 * categorical x positions" cleanly, so this is a small dependency-free SVG
 * renderer, mirroring paper_figures.py's paired_pre_post_figure exactly:
 * a slope line per unit from PRE to POST. Never computes delta_cycle or any
 * statistic -- purely positions the caller's own pre/post values. */
export default function PairedPrePostChart({
  data,
  yLabel,
  noDataReason,
}: {
  data: PairedPrePostDatum[] | null | undefined;
  yLabel: string;
  noDataReason: string;
}) {
  if (!data || data.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const values = data.flatMap((d) => [d.pre, d.post]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = maxValue - minValue || 1;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const yFor = (v: number) => PAD.top + plotHeight * (1 - (v - minValue) / span);
  const xPre = PAD.left;
  const xPost = PAD.left + plotWidth;

  return (
    <div className="overflow-x-auto">
      <svg role="img" aria-label={`Paired PRE/POST chart, ${yLabel}`} width={WIDTH} height={HEIGHT} viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
        <line x1={xPre} y1={PAD.top} x2={xPre} y2={PAD.top + plotHeight} stroke="#334155" />
        <line x1={xPost} y1={PAD.top} x2={xPost} y2={PAD.top + plotHeight} stroke="#334155" />
        <text x={xPre} y={HEIGHT - 8} fill="#94a3b8" fontSize={11} textAnchor="middle">PRE</text>
        <text x={xPost} y={HEIGHT - 8} fill="#94a3b8" fontSize={11} textAnchor="middle">POST</text>
        <text x={12} y={PAD.top} fill="#94a3b8" fontSize={10} transform={`rotate(-90 12 ${PAD.top + plotHeight / 2})`} textAnchor="middle">
          {yLabel}
        </text>
        {data.map((d) => (
          <g key={d.unitId} data-testid="paired-pre-post-line">
            <line x1={xPre} y1={yFor(d.pre)} x2={xPost} y2={yFor(d.post)} stroke="#2b6cb0" strokeWidth={1.5} opacity={0.8} />
            <circle cx={xPre} cy={yFor(d.pre)} r={3} fill="#2b6cb0" />
            <circle cx={xPost} cy={yFor(d.post)} r={3} fill="#2b6cb0" />
            <text x={xPost + 8} y={yFor(d.post)} fill="#cbd5e1" fontSize={10} dominantBaseline="middle">{d.unitId}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
