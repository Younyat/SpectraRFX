import { Bar, BarChart, CartesianGrid, ErrorBar, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import NoDataNotice from '../NoDataNotice';

export interface BarWithCiDatum {
  category: string;
  value: number;
  /** Absolute CI bounds (not offsets) -- omit both on a datum whose CI is
   * not available; this renderer never fabricates a 0-width interval. */
  ciLow?: number | null;
  ciHigh?: number | null;
}

/** RQ1 BA-by-domain, RQ2 BA/macro-F1/coverage-by-branch, S1 per-channel BA.
 * Pure renderer: every number comes from the caller's already-computed
 * report -- this component computes nothing. Renders NoDataNotice when
 * `data` is missing or empty, never a zeroed axis. */
export default function BarWithCiChart({
  data,
  yLabel,
  noDataReason,
}: {
  data: BarWithCiDatum[] | null | undefined;
  yLabel: string;
  noDataReason: string;
}) {
  if (!data || data.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const chartData = data.map((d) => ({
    ...d,
    errorRange: d.ciLow != null && d.ciHigh != null ? [Math.max(0, d.value - d.ciLow), Math.max(0, d.ciHigh - d.value)] : undefined,
  }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="category" tick={{ fill: '#94a3b8', fontSize: 11 }} angle={-15} textAnchor="end" height={50} />
        <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }} />
        <Bar dataKey="value" fill="#2b6cb0" isAnimationActive={false}>
          <ErrorBar dataKey="errorRange" width={4} strokeWidth={1.5} stroke="#e2e8f0" direction="y" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
