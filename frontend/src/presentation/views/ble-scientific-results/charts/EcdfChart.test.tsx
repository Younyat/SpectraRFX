import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import EcdfChart from './EcdfChart';
import { ECDF_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('EcdfChart', () => {
  it('renders a step line when given real fixture values', () => {
    const { container } = render(<EcdfChart values={ECDF_SYNTHETIC_FIXTURE} xLabel="latency (ms)" noDataReason="n/a" />);
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull();
  });

  it('renders NO DATA when values is empty', () => {
    render(<EcdfChart values={[]} xLabel="latency (ms)" noDataReason="no near-live latency samples measured yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
