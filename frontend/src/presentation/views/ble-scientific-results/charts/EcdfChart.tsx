import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import NoDataNotice from '../NoDataNotice';

/** Empirical CDF of a real, already-measured sample (e.g. offline/near-live
 * latency) -- a real step function, not a histogram density estimate. The
 * ECDF itself (sorting + rank/n) is a display transform of already-real
 * numbers, not a new statistical test. */
export default function EcdfChart({
  values,
  xLabel,
  noDataReason,
}: {
  values: number[] | null | undefined;
  xLabel: string;
  noDataReason: string;
}) {
  if (!values || values.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const data = sorted.map((v, i) => ({ value: v, ecdf: (i + 1) / n }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis type="number" dataKey="value" tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: xLabel, position: 'insideBottom', offset: -4, fill: '#94a3b8', fontSize: 11 }} />
        <YAxis type="number" dataKey="ecdf" domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: 'ECDF', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }} />
        <Line type="step" dataKey="ecdf" stroke="#2b6cb0" dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
