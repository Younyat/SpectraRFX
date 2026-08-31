import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RFTerrainView } from '../ui/RFTerrainView';
import { RFTerrainModuleBoundary } from '../../../app/modules/rf-terrain/RFTerrainModuleBoundary';

describe('RFTerrainView', () => {
  it('falls back to the 2D view when WebGL is unavailable, with a legacy Waterfall escape hatch', () => {
    render(
      <MemoryRouter>
        <RFTerrainView />
      </MemoryRouter>,
    );
    // jsdom has no WebGL context -- the same fail-closed path a browser
    // without WebGL support would take (spec §3/§53): RFTerrainView drops
    // straight to RFTerrainFallback2D instead of mounting Three.js.
    expect(screen.getByText(/2D fallback mode/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Waterfall/i })).toHaveAttribute('href', '/waterfall');
  });
});

const Boom: React.FC = () => {
  throw new Error('synthetic rf-terrain render failure');
};

describe('RFTerrainModuleBoundary', () => {
  it('contains a local render failure instead of letting it escape to the rest of the app', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <MemoryRouter>
        <RFTerrainModuleBoundary>
          <Boom />
        </RFTerrainModuleBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByText('RF Terrain no disponible')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Waterfall/i })).toHaveAttribute('href', '/waterfall');
    consoleErrorSpy.mockRestore();
  });

  it('renders children normally when nothing fails', () => {
    render(
      <MemoryRouter>
        <RFTerrainModuleBoundary>
          <div>rf-terrain ok</div>
        </RFTerrainModuleBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByText('rf-terrain ok')).toBeInTheDocument();
    expect(screen.queryByText('RF Terrain no disponible')).not.toBeInTheDocument();
  });
});
