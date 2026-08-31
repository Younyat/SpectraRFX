import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import EvidenceMaturityBadge from './EvidenceMaturityBadge';

describe('EvidenceMaturityBadge', () => {
  it('renders the exact maturity it is given, never a different one', () => {
    render(<EvidenceMaturityBadge maturity="VALIDATION" />);
    expect(screen.getByText('VALIDATION')).toBeInTheDocument();
    expect(screen.queryByText('CONFIRMATORY')).not.toBeInTheDocument();
  });

  it('a VALIDATION badge and a CONFIRMATORY badge render visually distinct tones', () => {
    const { container: validationContainer } = render(<EvidenceMaturityBadge maturity="VALIDATION" />);
    const { container: confirmatoryContainer } = render(<EvidenceMaturityBadge maturity="CONFIRMATORY" />);
    const validationClass = validationContainer.querySelector('span')?.className;
    const confirmatoryClass = confirmatoryContainer.querySelector('span')?.className;
    expect(validationClass).not.toBe(confirmatoryClass);
  });

  it.each(['QUALIFICATION', 'DEVELOPMENT', 'VALIDATION', 'CONFIRMATORY', 'ENGINEERING'] as const)('renders %s as its own literal label', (maturity) => {
    render(<EvidenceMaturityBadge maturity={maturity} />);
    expect(screen.getByText(maturity)).toBeInTheDocument();
  });
});
