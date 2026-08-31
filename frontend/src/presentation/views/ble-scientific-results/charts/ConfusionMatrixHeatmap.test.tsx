import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ConfusionMatrixHeatmap from './ConfusionMatrixHeatmap';
import { CONFUSION_MATRIX_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('ConfusionMatrixHeatmap', () => {
  it('renders one cell per (true, predicted) pair when given a real fixture matrix', () => {
    const { container } = render(<ConfusionMatrixHeatmap matrix={CONFUSION_MATRIX_SYNTHETIC_FIXTURE} noDataReason="n/a" />);
    const labelCount = Object.keys(CONFUSION_MATRIX_SYNTHETIC_FIXTURE).length;
    expect(container.querySelectorAll('[data-testid="confusion-cell"]').length).toBe(labelCount * labelCount);
    expect(screen.getAllByText('8').length).toBeGreaterThan(0);
  });

  it('renders NO DATA when matrix is null', () => {
    render(<ConfusionMatrixHeatmap matrix={null} noDataReason="no confusion matrix persisted yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
    expect(screen.getByText('no confusion matrix persisted yet')).toBeInTheDocument();
  });

  it('renders NO DATA when matrix has no labels', () => {
    render(<ConfusionMatrixHeatmap matrix={{}} noDataReason="empty matrix" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
