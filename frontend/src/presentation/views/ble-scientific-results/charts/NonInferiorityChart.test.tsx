import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import NonInferiorityChart from './NonInferiorityChart';
import { NON_INFERIORITY_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('NonInferiorityChart', () => {
  it('renders one forest-plot row and the decision-boundary reference line when given real fixture data', () => {
    const { container } = render(<NonInferiorityChart data={NON_INFERIORITY_SYNTHETIC_FIXTURE} noDataReason="n/a" />);
    expect(container.querySelectorAll('[data-testid="non-inferiority-row"]').length).toBe(NON_INFERIORITY_SYNTHETIC_FIXTURE.length);
    expect(screen.getByText('FULL_BURST vs ADVA_EXCLUDED')).toBeInTheDocument();
    expect(screen.getByText(/frontera/)).toBeInTheDocument();
  });

  it('renders NO DATA and no SVG rows when data is empty', () => {
    const { container } = render(<NonInferiorityChart data={[]} noDataReason="no rq4 non-inferiority result yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-testid="non-inferiority-row"]').length).toBe(0);
  });

  it('renders NO DATA when data is null', () => {
    render(<NonInferiorityChart data={null} noDataReason="no rq4 non-inferiority result yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
