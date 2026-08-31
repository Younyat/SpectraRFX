import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import HistogramChart from './HistogramChart';
import { HISTOGRAM_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('HistogramChart', () => {
  it('renders binned bars when given real fixture values', () => {
    const { container } = render(<HistogramChart values={HISTOGRAM_SYNTHETIC_FIXTURE} bins={5} xLabel="delta_cycle" noDataReason="n/a" />);
    expect(container.querySelectorAll('.recharts-bar-rectangle').length).toBeGreaterThan(0);
  });

  it('shows the observed statistic when supplied', () => {
    render(<HistogramChart values={HISTOGRAM_SYNTHETIC_FIXTURE} observedValue={0.025} xLabel="delta_cycle" noDataReason="n/a" />);
    expect(screen.getByText('0.025')).toBeInTheDocument();
  });

  it('renders NO DATA when values is empty', () => {
    render(<HistogramChart values={[]} xLabel="delta_cycle" noDataReason="no permutation draws persisted yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
