import { Search, RotateCw } from 'lucide-react';
import type { ReceiverFilters } from '../../../domain/kiwisdr/Receiver';

export function ReceiverFiltersPanel({
  filters,
  countries,
  isRefreshing,
  onChange,
  onRefresh,
}: {
  filters: ReceiverFilters;
  countries: string[];
  isRefreshing: boolean;
  onChange: (filters: ReceiverFilters) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="border-b border-slate-800 bg-slate-900 px-4 py-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[260px] flex-col gap-1 text-xs text-slate-400">
          Search receiver
          <div className="flex h-10 items-center rounded-md border border-slate-700 bg-slate-950 px-3">
            <Search className="mr-2 h-4 w-4 text-slate-500" />
            <input
              value={filters.q}
              onChange={(event) => onChange({ ...filters, q: event.target.value })}
              className="w-full bg-transparent text-sm text-slate-100 outline-none"
              placeholder="host, city, country, name"
            />
          </div>
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Country
          <select
            value={filters.country}
            onChange={(event) => onChange({ ...filters, country: event.target.value })}
            className="h-10 w-48 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none"
          >
            <option value="">All countries</option>
            {countries.map((country) => (
              <option key={country} value={country}>{country}</option>
            ))}
          </select>
        </label>

        <label className="flex h-10 items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={filters.onlineOnly}
            onChange={(event) => onChange({ ...filters, onlineOnly: event.target.checked })}
          />
          Online only
        </label>

        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className="inline-flex h-10 items-center rounded-md bg-cyan-600 px-3 text-sm font-semibold text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-700"
        >
          <RotateCw className="mr-2 h-4 w-4" />
          {isRefreshing ? 'Refreshing' : 'Refresh catalog'}
        </button>
      </div>
    </div>
  );
}
