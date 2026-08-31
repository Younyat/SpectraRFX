import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import NoDataNotice from '../NoDataNotice';

/** RQ3 permutation-test null distribution + observed statistic overlay,
 * or any other real distribution the export needs to show. Equal-width
 * binning of already-real draws is a display transform, not a new
 * statistical computation -- the caller supplies the real permutation
 * draws themselves. */
export default function HistogramChart({
  values,
  bins = 20,
  observedValue,
  xLabel,
  noDataReason,
}: {
  values: number[] | null | undefined;
  bins?: number;
  observedValue?: number | null;
  xLabel: string;
  noDataReason: string;
}) {
  if (!values || values.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = span / bins;
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - min) / width)));
    counts[idx] += 1;
  }
  const data = counts.map((count, i) => ({
    bin: `${(min + i * width).toFixed(2)}`,
    count,
  }));
  return (
    <div className="space-y-1">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="bin" tick={{ fill: '#94a3b8', fontSize: 10 }} angle={-45} textAnchor="end" height={50} label={{ value: xLabel, position: 'insideBottom', offset: -4, fill: '#94a3b8', fontSize: 11 }} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: 'count', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }} />
          <Bar dataKey="count" fill="#2b6cb0" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      {observedValue != null && (
        <div className="text-[11px] text-slate-400">observed statistic: <span className="font-mono text-slate-200">{observedValue}</span></div>
      )}
    </div>
  );
}
