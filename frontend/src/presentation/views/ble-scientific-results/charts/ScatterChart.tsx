import { CartesianGrid, Scatter, ScatterChart as RechartsScatterChart, ResponsiveContainer, XAxis, YAxis, ZAxis } from 'recharts';
import NoDataNotice from '../NoDataNotice';

export interface ScatterDatum {
  label: string;
  x: number;
  y: number;
}

/** RQ2 performance-vs-latency (or any other real x/y pair the caller
 * already has, one point per branch/unit/condition) -- pure renderer, no
 * regression line or fit is computed here. */
export default function ScatterChart({
  data,
  xLabel,
  yLabel,
  noDataReason,
}: {
  data: ScatterDatum[] | null | undefined;
  xLabel: string;
  yLabel: string;
  noDataReason: string;
}) {
  if (!data || data.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  return (
    <ResponsiveContainer width="100%" height={280}>
      <RechartsScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis type="number" dataKey="x" name={xLabel} tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: xLabel, position: 'insideBottom', offset: -4, fill: '#94a3b8', fontSize: 11 }} />
        <YAxis type="number" dataKey="y" name={yLabel} tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }} />
        <ZAxis range={[80, 80]} />
        <Scatter data={data} fill="#2b6cb0" isAnimationActive={false} />
      </RechartsScatterChart>
    </ResponsiveContainer>
  );
}
