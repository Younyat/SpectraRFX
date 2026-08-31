import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useRFTerrainFrameSource } from '../data/useRFTerrainFrameSource';

describe('useRFTerrainFrameSource', () => {
  it('reports DISABLED and touches neither the network nor a Worker when enabled=false', () => {
    const { result } = renderHook(() => useRFTerrainFrameSource({ enabled: false }));
    expect(result.current.diagnostics.state).toBe('DISABLED');
    expect(result.current.diagnostics.framesReceived).toBe(0);
  });
});
