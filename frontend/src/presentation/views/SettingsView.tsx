import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, RefreshCw, RotateCcw, Save } from 'lucide-react';
import { ApiService } from '../../app/services/ApiService';
import { useDeviceStatus } from '../../app/store/AppStore';
import { cn } from '../../shared/utils';

type RuntimeSetting = {
  key: string;
  section: string;
  tab: string;
  type: 'number' | 'string' | 'boolean';
  value: string | number | boolean;
  default: string | number | boolean;
  min?: number;
  max?: number;
  unit?: string;
  description: string;
  impact: string;
  restart_required: boolean;
  limit_kind: 'hardware' | 'software' | 'scientific_policy';
  risk: 'low' | 'medium' | 'high';
  source: 'saved' | 'env' | 'default';
};

type RuntimeSettingsPayload = {
  settings_path: string;
  requires_restart_after_save: boolean;
  items: RuntimeSetting[];
  values: Record<string, string | number | boolean>;
  status?: string;
};

const api = new ApiService();

const limitLabel = (kind: RuntimeSetting['limit_kind']) => {
  if (kind === 'hardware') return 'Hardware limit';
  if (kind === 'scientific_policy') return 'Scientific policy';
  return 'Software restriction';
};

const formatLimit = (item: RuntimeSetting) => {
  if (typeof item.min === 'number' && typeof item.max === 'number') {
    return `${item.min} - ${item.max}${item.unit ? ` ${item.unit}` : ''}`;
  }
  if (typeof item.min === 'number') return `min ${item.min}${item.unit ? ` ${item.unit}` : ''}`;
  if (typeof item.max === 'number') return `max ${item.max}${item.unit ? ` ${item.unit}` : ''}`;
  return item.limit_kind === 'hardware' ? 'Depends on connected hardware' : 'No numeric range';
};

export const SettingsView: React.FC = () => {
  const deviceStatus = useDeviceStatus();
  const [payload, setPayload] = useState<RuntimeSettingsPayload | null>(null);
  const [values, setValues] = useState<Record<string, string | number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSettings = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getRuntimeSettings() as RuntimeSettingsPayload;
      setPayload(data);
      setValues(data.values ?? {});
    } catch (err) {
      console.error('Failed to load runtime settings:', err);
      setError('No se pudo cargar la configuracion runtime desde el backend.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const grouped = useMemo(() => {
    const groups: Record<string, RuntimeSetting[]> = {};
    for (const item of payload?.items ?? []) {
      groups[item.section] = [...(groups[item.section] ?? []), item];
    }
    return groups;
  }, [payload]);

  const updateValue = (item: RuntimeSetting, raw: string | boolean) => {
    const value = item.type === 'number' ? Number(raw) : raw;
    setValues(prev => ({ ...prev, [item.key]: value }));
  };

  const resetToLoaded = () => {
    setValues(payload?.values ?? {});
    setMessage(null);
    setError(null);
  };

  const saveSettings = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const data = await api.saveRuntimeSettings(values) as RuntimeSettingsPayload;
      setPayload(data);
      setValues(data.values ?? {});
      setMessage('Guardado. Reinicia el programa para que backend, workers SDR y frontend lean estos valores.');
    } catch (err: any) {
      console.error('Failed to save runtime settings:', err);
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail ?? 'No se pudo guardar la configuracion.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full overflow-auto bg-gray-50">
      <div className="mx-auto max-w-7xl p-6 space-y-5">
        <div className="flex flex-col gap-4 border-b border-gray-200 pb-5 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-950">Runtime Settings</h2>
            <p className="mt-1 max-w-3xl text-sm text-gray-600">
              Parametros editables usados por hardware, captura, espectro, waterfall, RF Intelligence y QC de datasets.
              Los limites que no son de hardware aparecen en rojo porque son restricciones del software o politica cientifica.
            </p>
            {payload?.settings_path && (
              <p className="mt-2 text-xs text-gray-500">Persistencia: {payload.settings_path}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={loadSettings}
              disabled={loading || saving}
              className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" />
              Reload
            </button>
            <button
              type="button"
              onClick={resetToLoaded}
              disabled={loading || saving || !payload}
              className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              <RotateCcw className="h-4 w-4" />
              Reset
            </button>
            <button
              type="button"
              onClick={saveSettings}
              disabled={loading || saving || !payload}
              className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              {saving ? 'Saving' : 'Save'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div className="rounded-md border border-gray-200 bg-white p-4">
            <div className="text-xs font-medium uppercase text-gray-500">Device</div>
            <div className={cn('mt-1 text-sm font-semibold', deviceStatus.isConnected ? 'text-green-700' : 'text-red-700')}>
              {deviceStatus.isConnected ? 'Connected' : 'Disconnected'}
            </div>
          </div>
          <div className="rounded-md border border-gray-200 bg-white p-4">
            <div className="text-xs font-medium uppercase text-gray-500">Driver</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">{deviceStatus.driver}</div>
          </div>
          <div className="rounded-md border border-gray-200 bg-white p-4">
            <div className="text-xs font-medium uppercase text-gray-500">Live sample rate</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">{deviceStatus.sampleRate.toLocaleString()} samples/s</div>
          </div>
          <div className="rounded-md border border-gray-200 bg-white p-4">
            <div className="text-xs font-medium uppercase text-gray-500">Live gain</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">{deviceStatus.gain.toFixed(1)} dB</div>
          </div>
        </div>

        {message && (
          <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">{message}</div>
        )}
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>
        )}

        {loading ? (
          <div className="rounded-md border border-gray-200 bg-white p-6 text-sm text-gray-600">Loading runtime settings...</div>
        ) : (
          Object.entries(grouped).map(([section, items]) => (
            <section key={section} className="rounded-md border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-4 py-3">
                <h3 className="text-sm font-semibold text-gray-950">{section}</h3>
              </div>
              <div className="divide-y divide-gray-200">
                {items.map(item => {
                  const nonHardwareLimit = item.limit_kind !== 'hardware';
                  const highRisk = item.risk === 'high';
                  const value = values[item.key] ?? item.value ?? item.default;
                  return (
                    <div key={item.key} className="grid grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[minmax(220px,0.9fr)_minmax(260px,1.1fr)_minmax(260px,1fr)]">
                      <div>
                        <div className="font-mono text-sm font-semibold text-gray-950">{item.key}</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <span className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-700">{item.source}</span>
                          <span className={cn(
                            'rounded px-2 py-1 text-xs font-medium',
                            nonHardwareLimit ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'
                          )}>
                            {limitLabel(item.limit_kind)}
                          </span>
                          {item.restart_required && (
                            <span className="rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800">Restart required</span>
                          )}
                        </div>
                      </div>

                      <div className="space-y-2 text-sm">
                        <div>
                          <span className="font-medium text-gray-700">Pestana afectada: </span>
                          <span className="text-gray-700">{item.tab}</span>
                        </div>
                        <p className="text-gray-600">{item.description}</p>
                        <p className="text-gray-700">{item.impact}</p>
                        <div className={cn('flex items-center gap-2 text-xs', nonHardwareLimit || highRisk ? 'text-red-700' : 'text-gray-500')}>
                          {(nonHardwareLimit || highRisk) && <AlertTriangle className="h-4 w-4 shrink-0" />}
                          <span>Limites: {formatLimit(item)}</span>
                        </div>
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-medium uppercase text-gray-500">
                          Value {item.unit ? `(${item.unit})` : ''}
                        </label>
                        {item.type === 'boolean' ? (
                          <input
                            type="checkbox"
                            checked={Boolean(value)}
                            onChange={event => updateValue(item, event.target.checked)}
                            className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                        ) : (
                          <input
                            type={item.type === 'number' ? 'number' : 'text'}
                            value={String(value)}
                            min={item.min}
                            max={item.max}
                            step={item.type === 'number' ? 'any' : undefined}
                            onChange={event => updateValue(item, event.target.value)}
                            className={cn(
                              'w-full rounded-md border px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-500',
                              nonHardwareLimit ? 'border-red-300 bg-red-50/40' : 'border-gray-300 bg-white'
                            )}
                          />
                        )}
                        <div className="mt-2 text-xs text-gray-500">Default: {String(item.default)}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))
        )}
      </div>
    </div>
  );
};
