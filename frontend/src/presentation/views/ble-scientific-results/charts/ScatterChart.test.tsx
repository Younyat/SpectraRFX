import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ScatterChart from './ScatterChart';
import { SCATTER_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('ScatterChart', () => {
  it('renders one point per datum when given real fixture data', () => {
    const { container } = render(<ScatterChart data={SCATTER_SYNTHETIC_FIXTURE} xLabel="latency" yLabel="BA" noDataReason="n/a" />);
    expect(container.querySelectorAll('.recharts-scatter-symbol').length).toBe(SCATTER_SYNTHETIC_FIXTURE.length);
  });

  it('renders NO DATA and no chart when data is empty', () => {
    render(<ScatterChart data={[]} xLabel="latency" yLabel="BA" noDataReason="no rq2 data yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
    expect(screen.getByText('no rq2 data yet')).toBeInTheDocument();
  });

  it('renders NO DATA when data is null', () => {
    render(<ScatterChart data={null} xLabel="latency" yLabel="BA" noDataReason="no rq2 data yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
