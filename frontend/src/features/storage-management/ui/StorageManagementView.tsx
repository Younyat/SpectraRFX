import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, ChevronRight, Database, File as FileIcon, Folder,
  HardDrive, Lock, RefreshCw, Trash2,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { StorageManagementApiError, StorageManagementClient } from '../api/storageManagementClient';
import type { StorageCategory, StorageItem, StorageSummary } from '../types';

const client = new StorageManagementClient();
const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_42px_rgba(15,23,42,0.07)]';

// A fixed, chosen categorical palette (never a rainbow default) -- reused
// cyclically across however many real categories the storage root happens
// to have, so it stays legible whether there are 3 categories or 12.
const CATEGORY_COLORS = ['#2b6cb0', '#0d9488', '#b45309', '#7c3aed', '#be123c', '#0369a1', '#65a30d', '#c2410c'];

const formatBytes = (bytes: number): string => {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

const formatDateTime = (iso: string | null | undefined): string => {
  if (!iso) return 'unknown';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'unknown';
  return date.toLocaleString();
};

const itemKindLabel: Record<StorageItem['kind'], string> = {
  directory: 'Folder',
  file: 'File',
  ble_capture: 'BLE I/Q capture',
  ble_capture_incomplete: 'BLE I/Q capture (no manifest)',
};

// Every real, isolated storage-management route -- no other feature reads
// or writes through this view; deleting is confirmation-gated end to end
// (this component's modal, then the backend's own `confirm=True` check).
export const StorageManagementView: React.FC = () => {
  const [summary, setSummary] = useState<StorageSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [items, setItems] = useState<StorageItem[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<StorageItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const refreshSummary = async () => {
    setSummaryLoading(true);
    try {
      setSummary(await client.fetchSummary());
    } catch (e) {
      setError(e instanceof StorageManagementApiError ? e.message : String(e));
    } finally {
      setSummaryLoading(false);
    }
  };

  const refreshItems = async (path: string) => {
    setItemsLoading(true);
    try {
      const response = await client.fetchItems(path);
      setItems(response.items);
    } catch (e) {
      setError(e instanceof StorageManagementApiError ? e.message : String(e));
    } finally {
      setItemsLoading(false);
    }
  };

  useEffect(() => {
    refreshSummary().catch(() => {});
  }, []);

  useEffect(() => {
    if (currentPath !== null) {
      refreshItems(currentPath).catch(() => {});
    }
  }, [currentPath]);

  const openCategory = (relativePath: string) => {
    setError(null);
    setCurrentPath(relativePath);
  };

  const openDirectoryItem = (item: StorageItem) => {
    if (item.kind !== 'directory') return;
    setError(null);
    setCurrentPath(item.item_id);
  };

  const breadcrumbSegments = useMemo(() => (currentPath ? currentPath.split('/') : []), [currentPath]);

  const goToBreadcrumb = (index: number) => {
    if (index < 0) {
      setCurrentPath(null);
      return;
    }
    setCurrentPath(breadcrumbSegments.slice(0, index + 1).join('/'));
  };

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    setDeleting(true);
    setError(null);
    try {
      await client.deleteItem(confirmTarget.item_id, true);
      setConfirmTarget(null);
      if (currentPath !== null) await refreshItems(currentPath);
      await refreshSummary();
    } catch (e) {
      setError(e instanceof StorageManagementApiError ? e.message : String(e));
    } finally {
      setDeleting(false);
    }
  };

  const chartData = useMemo(
    () => (summary?.categories ?? []).map((category, index) => ({
      name: category.name,
      bytes: category.total_bytes,
      color: CATEGORY_COLORS[index % CATEGORY_COLORS.length],
    })),
    [summary],
  );

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center gap-3">
        <HardDrive className="h-7 w-7 text-indigo-600" />
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Storage &amp; Artifact Repository</h1>
          <p className="text-sm text-slate-500">
            Real, filesystem-measured disk usage across every capture, dataset, and artifact category. Nothing is
            estimated or cached -- every number here is read from disk at request time.
          </p>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <p>{error}</p>
        </div>
      )}

      {/* Overview */}
      <section className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-800"><Database className="h-5 w-5" /> Overview</h2>
          <button onClick={() => refreshSummary()} className="flex items-center gap-1 text-xs text-indigo-600 hover:underline">
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>

        {summaryLoading && !summary && <p className="text-sm text-slate-500">Scanning storage…</p>}

        {summary && (
          <>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] font-semibold uppercase text-slate-400">Total on disk</div>
                <div className="text-xl font-semibold text-slate-800">{formatBytes(summary.total_bytes)}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] font-semibold uppercase text-slate-400">Total files</div>
                <div className="text-xl font-semibold text-slate-800">{summary.total_file_count.toLocaleString()}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-[10px] font-semibold uppercase text-slate-400">Categories</div>
                <div className="text-xl font-semibold text-slate-800">{summary.categories.length}</div>
              </div>
            </div>

            {chartData.length > 0 && (
              <ResponsiveContainer width="100%" height={Math.max(160, chartData.length * 34)}>
                <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" tickFormatter={formatBytes} tick={{ fill: '#64748b', fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" width={140} tick={{ fill: '#334155', fontSize: 12 }} />
                  <Tooltip formatter={(value: number) => formatBytes(value)} />
                  <Bar dataKey="bytes" isAnimationActive={false} radius={[0, 4, 4, 0]}>
                    {chartData.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </>
        )}
      </section>

      {/* Categories */}
      {currentPath === null && summary && (
        <section className={card}>
          <h2 className="mb-3 text-lg font-semibold text-slate-800">Categories</h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {summary.categories.map((category) => (
              <CategoryCard key={category.name} category={category} onOpen={() => openCategory(category.relative_path)} />
            ))}
          </div>
        </section>
      )}

      {/* Drill-down items */}
      {currentPath !== null && (
        <section className={card}>
          <div className="mb-3 flex items-center justify-between">
            <nav className="flex items-center gap-1 text-sm text-slate-500">
              <button onClick={() => goToBreadcrumb(-1)} className="text-indigo-600 hover:underline">All categories</button>
              {breadcrumbSegments.map((segment, index) => (
                <React.Fragment key={segment + index}>
                  <ChevronRight className="h-3.5 w-3.5" />
                  <button onClick={() => goToBreadcrumb(index)} className="text-indigo-600 hover:underline">{segment}</button>
                </React.Fragment>
              ))}
            </nav>
            <button onClick={() => refreshItems(currentPath)} className="flex items-center gap-1 text-xs text-indigo-600 hover:underline">
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>
          </div>

          {itemsLoading && <p className="text-sm text-slate-500">Loading…</p>}
          {!itemsLoading && items.length === 0 && <p className="text-sm text-slate-500">Empty.</p>}

          <div className="flex flex-col gap-1.5">
            {items.map((item) => (
              <ItemRow key={item.item_id} item={item} onOpen={() => openDirectoryItem(item)} onRequestDelete={() => setConfirmTarget(item)} />
            ))}
          </div>
        </section>
      )}

      {confirmTarget && (
        <DeleteConfirmModal
          item={confirmTarget}
          deleting={deleting}
          onCancel={() => setConfirmTarget(null)}
          onConfirm={handleConfirmDelete}
        />
      )}
    </div>
  );
};

const CategoryCard: React.FC<{ category: StorageCategory; onOpen: () => void }> = ({ category, onOpen }) => (
  <button onClick={onOpen} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-left hover:border-indigo-300 hover:bg-indigo-50/40">
    <div className="flex items-center gap-2">
      <Folder className="h-4 w-4 text-slate-400" />
      <div>
        <div className="font-medium text-slate-800">{category.name}</div>
        <div className="text-[11px] text-slate-400">{category.file_count.toLocaleString()} files · updated {formatDateTime(category.last_modified_utc)}</div>
      </div>
    </div>
    <div className="text-right">
      <div className="font-mono text-sm font-semibold text-slate-700">{formatBytes(category.total_bytes)}</div>
      <ChevronRight className="ml-auto h-3.5 w-3.5 text-slate-300" />
    </div>
  </button>
);

const ItemRow: React.FC<{ item: StorageItem; onOpen: () => void; onRequestDelete: () => void }> = ({ item, onOpen, onRequestDelete }) => {
  const isDirectory = item.kind === 'directory';
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 px-3 py-2 text-sm">
      <button
        onClick={isDirectory ? onOpen : undefined}
        disabled={!isDirectory}
        className={`flex flex-1 items-center gap-2 text-left ${isDirectory ? 'hover:text-indigo-600' : 'cursor-default'}`}
      >
        {isDirectory ? <Folder className="h-4 w-4 flex-shrink-0 text-slate-400" /> : <FileIcon className="h-4 w-4 flex-shrink-0 text-slate-400" />}
        <div className="min-w-0">
          <div className="truncate font-medium text-slate-800">{item.display_name}</div>
          <div className="text-[11px] text-slate-400">
            {itemKindLabel[item.kind]} · {item.file_count.toLocaleString()} file{item.file_count === 1 ? '' : 's'}
            {' · '}{item.created_at_utc ? `created ${formatDateTime(item.created_at_utc)}` : `modified ${formatDateTime(item.last_modified_utc)}`}
          </div>
        </div>
      </button>

      <span
        title={item.preserved_reason}
        className={`flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
          item.preserved ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-slate-200 bg-slate-50 text-slate-500'
        }`}
      >
        {item.preserved && <Lock className="h-2.5 w-2.5" />}
        {item.preserved ? 'Preserved' : 'Regenerable'}
      </span>

      <span className="w-24 flex-shrink-0 text-right font-mono text-xs font-semibold text-slate-700">{formatBytes(item.size_bytes)}</span>

      <button onClick={onRequestDelete} title="Delete" className="flex-shrink-0 text-slate-400 hover:text-red-600">
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
};

const DeleteConfirmModal: React.FC<{
  item: StorageItem;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}> = ({ item, deleting, onCancel, onConfirm }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
    <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl">
      <div className="mb-3 flex items-center gap-2 text-red-600">
        <AlertTriangle className="h-5 w-5" />
        <h3 className="text-lg font-semibold">Delete this artifact?</h3>
      </div>
      <p className="mb-1 text-sm text-slate-700">
        <span className="font-medium">{item.display_name}</span> ({formatBytes(item.size_bytes)}, {item.file_count.toLocaleString()} file{item.file_count === 1 ? '' : 's'})
      </p>
      <p className={`mb-4 rounded-lg p-2 text-xs ${item.preserved ? 'bg-amber-50 text-amber-800' : 'bg-slate-50 text-slate-600'}`}>
        {item.preserved_reason}
        {item.preserved && ' This action cannot be undone from within the platform.'}
      </p>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} disabled={deleting} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-40">
          Cancel
        </button>
        <button onClick={onConfirm} disabled={deleting} className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
          {deleting ? 'Deleting…' : 'Delete permanently'}
        </button>
      </div>
    </div>
  </div>
);
