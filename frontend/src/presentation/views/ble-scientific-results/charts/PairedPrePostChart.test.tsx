import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PairedPrePostChart from './PairedPrePostChart';
import { PAIRED_PRE_POST_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('PairedPrePostChart', () => {
  it('renders one PRE->POST line per unit when given real fixture data', () => {
    const { container } = render(<PairedPrePostChart data={PAIRED_PRE_POST_SYNTHETIC_FIXTURE} yLabel="delta" noDataReason="n/a" />);
    expect(container.querySelectorAll('[data-testid="paired-pre-post-line"]').length).toBe(PAIRED_PRE_POST_SYNTHETIC_FIXTURE.length);
    expect(screen.getByText('UNIT-A')).toBeInTheDocument();
    expect(screen.getByText('UNIT-B')).toBeInTheDocument();
  });

  it('renders NO DATA and no SVG lines when data is empty', () => {
    const { container } = render(<PairedPrePostChart data={[]} yLabel="delta" noDataReason="no rq3 pairs yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-testid="paired-pre-post-line"]').length).toBe(0);
  });
});
