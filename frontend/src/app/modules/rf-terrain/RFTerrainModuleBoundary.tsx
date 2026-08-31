import React from 'react';
import { Link } from 'react-router-dom';
import { RF_TERRAIN_LEGACY_WATERFALL_PATH } from '../../../features/rf-terrain/model/rfTerrainConstants';

interface RFTerrainModuleBoundaryState {
  hasError: boolean;
}

// Module-local boundary (spec §51): wraps ONLY the RF Terrain view. A crash
// inside this module must degrade to this fallback and nothing else --
// never bubble up into a whole-app error screen.
export class RFTerrainModuleBoundary extends React.Component<React.PropsWithChildren, RFTerrainModuleBoundaryState> {
  state: RFTerrainModuleBoundaryState = { hasError: false };

  static getDerivedStateFromError(): RFTerrainModuleBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error('[rf-terrain] local render failure, isolated from the rest of SpectraRFX', error);
  }

  private retry = () => this.setState({ hasError: false });

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-8 text-center">
        <div>
          <h2 className="text-lg font-semibold">RF Terrain no disponible</h2>
          <p className="mt-1 max-w-md text-sm app-muted-text">
            El resto de SpectraRFX sigue funcionando con normalidad.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={this.retry}
            className="rounded-full border px-4 py-2 text-sm"
            style={{ borderColor: 'var(--app-border)' }}
          >
            Reintentar Terrain
          </button>
          <Link
            to={RF_TERRAIN_LEGACY_WATERFALL_PATH}
            className="rounded-full border px-4 py-2 text-sm"
            style={{ borderColor: 'var(--app-border)' }}
          >
            Abrir Waterfall (legacy)
          </Link>
        </div>
      </div>
    );
  }
}
