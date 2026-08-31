import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import RiskCoverageChart from './RiskCoverageChart';
import { RISK_COVERAGE_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('RiskCoverageChart', () => {
  it('renders a line path when given real fixture points', () => {
    const { container } = render(<RiskCoverageChart points={RISK_COVERAGE_SYNTHETIC_FIXTURE} noDataReason="n/a" />);
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull();
  });

  it('renders NO DATA when points is empty', () => {
    render(<RiskCoverageChart points={[]} noDataReason="no risk_coverage in confirmatory_future_analysis_report.json yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
