import React from 'react';
import { useWaterfall } from '../hooks/useWaterfall';
import { useAnalyzerSettings } from '../../app/store/AppStore';
import { formatFrequency } from '../../shared/utils';

export const WaterfallView: React.FC = () => {
  const { canvasRef } = useWaterfall();
  const settings = useAnalyzerSettings();

  return (
    <div className="h-full flex flex-col">
      {/* Controls */}
      <div className="bg-white border-b border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium text-gray-900">Waterfall Display</h3>
          <div className="text-sm text-gray-600">
            Center: {formatFrequency(settings.centerFrequency)} | Span: {formatFrequency(settings.span)}
          </div>
        </div>
      </div>

      {/* Waterfall Display */}
      <div className="flex-1 relative bg-black">
        <canvas
          ref={canvasRef}
          width={1200}
          height={600}
          className="w-full h-full"
        />

        {/* Colorbar */}
        <div className="absolute right-4 top-4 bottom-4 w-8 bg-gradient-to-b from-blue-900 via-green-500 via-yellow-400 to-red-600 rounded">
          <div className="absolute -right-16 top-0 text-xs text-white">
            High Power
          </div>
          <div className="absolute -right-16 bottom-0 text-xs text-white">
            Low Power
          </div>
        </div>
      </div>

      {/* Status */}
      <div className="bg-white border-t border-gray-200 px-4 py-2">
        <div className="text-sm text-gray-600">
          Real-time frequency-time representation using Turbo colormap
        </div>
      </div>
    </div>
  );
};