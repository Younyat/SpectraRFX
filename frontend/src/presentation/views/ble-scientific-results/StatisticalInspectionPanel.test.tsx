import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import StatisticalInspectionPanel, { rq3PermutationRow, rq4PairedComparisonRow } from './StatisticalInspectionPanel';

describe('StatisticalInspectionPanel', () => {
  it('renders the no-data message and no table when every row is null', () => {
    render(<StatisticalInspectionPanel rows={[null, null]} noDataReason="no confirmatory result yet" />);
    expect(screen.getByText('no confirmatory result yet')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows MISSING_CANONICAL_METRIC for a field the real report does not carry, never a fabricated 0 or blank', () => {
    const report = { rq3_within_device_permutation_test: { status: 'EXECUTED', value: { observed_statistic: 1.2, n_permutations: 500, exact: true } } };
    render(<StatisticalInspectionPanel rows={[rq3PermutationRow(report)]} noDataReason="n/a" />);
    // p_value/CI were never supplied -> must read MISSING_CANONICAL_METRIC, never "0" or an empty cell.
    expect(screen.getAllByText('MISSING_CANONICAL_METRIC').length).toBeGreaterThan(0);
    expect(screen.queryByText('0.0000')).not.toBeInTheDocument();
  });

  it('rq3PermutationRow returns null (not a zeroed row) when the method never executed', () => {
    const report = { rq3_within_device_permutation_test: { status: 'SKIPPED_NO_DATA', value: null } };
    expect(rq3PermutationRow(report)).toBeNull();
  });

  it('rq4PairedComparisonRow reads the real contrast values verbatim, never recomputing mean_difference', () => {
    const report = {
      rq4_paired_comparison: {
        status: 'EXECUTED',
        value: { contrast: { mean_difference: -0.033, n_pairs: 7 }, randomization_test: { p_value: 0.041 } },
      },
    };
    const row = rq4PairedComparisonRow(report);
    expect(row?.estimate).toBe(-0.033);
    expect(row?.independentBlocks).toBe(7);
    expect(row?.rawP).toBe(0.041);
  });
});
