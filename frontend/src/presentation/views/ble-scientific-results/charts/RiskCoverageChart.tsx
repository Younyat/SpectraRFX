import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import NoDataNotice from '../NoDataNotice';

export interface RiskCoveragePoint {
  coverage: number;
  risk: number;
}

/** Selective-prediction risk-coverage curve, exactly the shape
 * risk_coverage_curve() already produces server-side (coverage on x, risk
 * on y). Pure renderer over already-computed points. */
export default function RiskCoverageChart({
  points,
  noDataReason,
}: {
  points: RiskCoveragePoint[] | null | undefined;
  noDataReason: string;
}) {
  if (!points || points.length === 0) {
    return <NoDataNotice reason={noDataReason} />;
  }
  const sorted = [...points].sort((a, b) => a.coverage - b.coverage);
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={sorted} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis type="number" dataKey="coverage" domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: 'coverage', position: 'insideBottom', offset: -4, fill: '#94a3b8', fontSize: 11 }} />
        <YAxis type="number" dataKey="risk" tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: 'risk', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }} />
        <Line type="monotone" dataKey="risk" stroke="#2b6cb0" dot={{ r: 2 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
