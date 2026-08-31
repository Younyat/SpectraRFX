import { useCallback, useEffect, useState } from 'react';
import { BleScientificResultsApiService, PartitionCompositionTable, ReceiverEpochRow, TxCompositionRow } from '../../../app/services/bleScientificResultsApi';
import { BleRffiStudioApiService, StudioLabelProvenanceReport } from '../../../app/services/bleRffiStudioApi';
import NoDataNotice from './NoDataNotice';

const sciApi = new BleScientificResultsApiService();
const studioApi = new BleRffiStudioApiService();

function TxCompositionTable({ rows }: { rows: TxCompositionRow[] }) {
  if (rows.length === 0) return <NoDataNotice reason="Ningun physical_unit registrado todavia en PhysicalDeviceRegistry." />;
  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">physical_unit_id</th>
            <th className="px-3 py-2 text-left">device_family</th>
            <th className="px-3 py-2 text-left">manufacturer / model</th>
            <th className="px-3 py-2 text-left">status</th>
            <th className="px-3 py-2 text-left">rq4_eligibility</th>
            <th className="px-3 py-2 text-right">capturas reales</th>
            <th className="px-3 py-2 text-left">canales</th>
            <th className="px-3 py-2 text-left">rango de dias</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={row.physical_unit_id}>
              <td className="px-3 py-2 font-mono text-slate-300">{row.physical_unit_id}</td>
              <td className="px-3 py-2 text-slate-300">{row.device_family ?? '—'}</td>
              <td className="px-3 py-2 text-slate-400">{[row.manufacturer, row.model].filter(Boolean).join(' / ') || '—'}</td>
              <td className="px-3 py-2 text-slate-400">{row.status ?? '—'}</td>
              <td className="px-3 py-2 text-slate-400">{row.rq4_eligibility ?? '—'}</td>
              <td className="px-3 py-2 text-right font-mono text-slate-300">{row.real_capture_count}</td>
              <td className="px-3 py-2 font-mono text-slate-400">{row.channels.join(', ') || '—'}</td>
              <td className="px-3 py-2 font-mono text-slate-400">{row.day_range ? `${row.day_range.first} .. ${row.day_range.last}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PartitionCompositionSection({ table, datasetId, datasetVersion, scientificTask, setDatasetId, setDatasetVersion, setScientificTask, onLoad, loading }: {
  table: PartitionCompositionTable | null;
  datasetId: string; datasetVersion: string; scientificTask: string;
  setDatasetId: (v: string) => void; setDatasetVersion: (v: string) => void; setScientificTask: (v: string) => void;
  onLoad: () => void; loading: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="mb-1 block text-[10.5px] text-slate-500">dataset_id</label>
          <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-[10.5px] text-slate-500">dataset_version</label>
          <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetVersion} onChange={(e) => setDatasetVersion(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-[10.5px] text-slate-500">scientific_task</label>
          <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={scientificTask} onChange={(e) => setScientificTask(e.target.value)} />
        </div>
        <button
          type="button" onClick={onLoad} disabled={loading || !datasetId || !datasetVersion || !scientificTask}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? 'Cargando…' : 'Cargar particion'}
        </button>
      </div>

      {!table && <NoDataNotice reason="Introduce dataset_id/dataset_version/scientific_task de un split real y pulsa 'Cargar particion'." />}
      {table && (
        <div className="space-y-2">
          <div className="text-[11px] text-slate-500">
            split_status = <span className="font-mono text-slate-300">{table.split_status}</span>
            {' · '}leakage_check = <span className="font-mono text-slate-300">{table.leakage_check_status}</span>
          </div>
          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2 text-left">domain</th><th className="px-3 py-2 text-right">n_examples</th><th className="px-3 py-2 text-right">n_captures (acquisition groups)</th><th className="px-3 py-2 text-right">n_sessions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {(['TRAIN', 'VALIDATION', 'TEST'] as const).map((domain) => (
                  <tr key={domain}>
                    <td className="px-3 py-2 font-mono text-slate-300">{domain}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{table.domains[domain].n_examples}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{table.domains[domain].n_captures}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{table.domains[domain].n_sessions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ReceiverEpochTable({ rows }: { rows: ReceiverEpochRow[] }) {
  if (rows.length === 0) return <NoDataNotice reason="Ninguna captura real tiene receiver_epoch asignado todavia." />;
  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-950 text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">receiver_epoch</th>
            <th className="px-3 py-2 text-left">boundary_reason</th>
            <th className="px-3 py-2 text-right">n_captures</th>
            <th className="px-3 py-2 text-left">dias</th>
            <th className="px-3 py-2 text-left">canales</th>
            <th className="px-3 py-2 text-left">physical_units</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row) => (
            <tr key={row.receiver_epoch}>
              <td className="px-3 py-2 font-mono text-slate-300">{row.receiver_epoch}</td>
              <td className="px-3 py-2 text-slate-400">{row.boundary_reason ?? '—'}</td>
              <td className="px-3 py-2 text-right font-mono text-slate-300">{row.n_captures}</td>
              <td className="px-3 py-2 font-mono text-slate-400">{row.day_ids.join(', ') || '—'}</td>
              <td className="px-3 py-2 font-mono text-slate-400">{row.channels.join(', ') || '—'}</td>
              <td className="px-3 py-2 font-mono text-slate-400">{row.physical_units.join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LabelProvenanceSection({ datasetId, datasetVersion, setDatasetId, setDatasetVersion, report, onLoad, loading }: {
  datasetId: string; datasetVersion: string;
  setDatasetId: (v: string) => void; setDatasetVersion: (v: string) => void;
  report: StudioLabelProvenanceReport | null; onLoad: () => void; loading: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="mb-1 block text-[10.5px] text-slate-500">dataset_id</label>
          <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-[10.5px] text-slate-500">dataset_version</label>
          <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-cyan-600 focus:outline-none" value={datasetVersion} onChange={(e) => setDatasetVersion(e.target.value)} />
        </div>
        <button
          type="button" onClick={onLoad} disabled={loading || !datasetId || !datasetVersion}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? 'Cargando…' : 'Cargar procedencia'}
        </button>
      </div>
      {!report && <NoDataNotice reason="Introduce dataset_id/dataset_version de un dataset real y pulsa 'Cargar procedencia'." />}
      {report && (
        <div className="space-y-2">
          <div className="text-[11px] text-slate-500">
            total_examples = <span className="font-mono text-slate-300">{report.total_examples}</span>
            {' · '}strong_fraction = <span className="font-mono text-slate-300">{report.strong_fraction.toFixed(4)}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
            {Object.entries(report.counts).map(([status, count]) => (
              <div key={status} className="rounded border border-slate-800 bg-slate-950 p-2">
                <div className="text-slate-500">{status}</div>
                <div className="font-mono text-slate-200">{count}</div>
                <div className="font-mono text-[10px] text-slate-500">{(report.fractions[status] ?? 0).toFixed(4)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Paper-representation pass (2026-08-17) -- supporting tables the paper
 * needs beyond RQ1-4 themselves: TX composition (real captures per
 * enrolled unit), partition composition (real windows/captures/sessions
 * per TRAIN/VALIDATION/TEST for a real split), label provenance
 * (STRONG vs declared-isolation association, ground-truth foundation),
 * and receiver-epoch composition (channels/days/units per real receiver
 * session). Every row is a real cross-reference over already-real
 * registry/capture/split artifacts -- computes no new science. */
export default function SupportingTablesTab() {
  const [txRows, setTxRows] = useState<TxCompositionRow[]>([]);
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);

  const [epochRows, setEpochRows] = useState<ReceiverEpochRow[]>([]);
  const [epochLoading, setEpochLoading] = useState(false);
  const [epochError, setEpochError] = useState<string | null>(null);

  const [datasetId, setDatasetId] = useState('');
  const [datasetVersion, setDatasetVersion] = useState('');
  const [scientificTask, setScientificTask] = useState('MULTI_DEVICE_CLASSIFICATION');
  const [partitionTable, setPartitionTable] = useState<PartitionCompositionTable | null>(null);
  const [partitionLoading, setPartitionLoading] = useState(false);

  const [labelDatasetId, setLabelDatasetId] = useState('');
  const [labelDatasetVersion, setLabelDatasetVersion] = useState('');
  const [labelReport, setLabelReport] = useState<StudioLabelProvenanceReport | null>(null);
  const [labelLoading, setLabelLoading] = useState(false);

  const loadTx = useCallback(() => {
    setTxLoading(true);
    setTxError(null);
    sciApi.txComposition().then(setTxRows).catch(() => setTxError('No se pudo cargar la composicion por transmisor.')).finally(() => setTxLoading(false));
  }, []);
  const loadEpochs = useCallback(() => {
    setEpochLoading(true);
    setEpochError(null);
    sciApi.receiverEpochs().then(setEpochRows).catch(() => setEpochError('No se pudo cargar la tabla de receiver epochs.')).finally(() => setEpochLoading(false));
  }, []);
  const loadPartition = useCallback(() => {
    setPartitionLoading(true);
    setPartitionTable(null);
    sciApi.partitionComposition(datasetId, datasetVersion, scientificTask).then(setPartitionTable).catch(() => setPartitionTable(null)).finally(() => setPartitionLoading(false));
  }, [datasetId, datasetVersion, scientificTask]);
  const loadLabelProvenance = useCallback(() => {
    setLabelLoading(true);
    setLabelReport(null);
    studioApi.labelProvenance(labelDatasetId, labelDatasetVersion).then(setLabelReport).catch(() => setLabelReport(null)).finally(() => setLabelLoading(false));
  }, [labelDatasetId, labelDatasetVersion]);

  useEffect(() => { loadTx(); loadEpochs(); }, [loadTx, loadEpochs]);

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Tablas de soporte -- composicion experimental</div>
        <div className="mt-1 text-xs text-slate-500">
          Composicion por transmisor, particion (captures/acquisition-groups/windows), fundamento de ground truth
          (label provenance) y receiver epochs. Cada fila es una referencia cruzada real -- ningun numero se calcula
          aqui.
        </div>
      </div>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-400">Composicion experimental por TX (physical_unit)</h3>
          <button type="button" onClick={loadTx} disabled={txLoading} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10.5px] text-slate-300 hover:bg-slate-800 disabled:opacity-50">
            {txLoading ? 'Actualizando…' : 'Refrescar'}
          </button>
        </div>
        {txError && <NoDataNotice reason={txError} />}
        {!txError && <TxCompositionTable rows={txRows} />}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Captures / acquisition-groups / decision-windows por particion</h3>
        <PartitionCompositionSection
          table={partitionTable} datasetId={datasetId} datasetVersion={datasetVersion} scientificTask={scientificTask}
          setDatasetId={setDatasetId} setDatasetVersion={setDatasetVersion} setScientificTask={setScientificTask}
          onLoad={loadPartition} loading={partitionLoading}
        />
      </section>

      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Fundamento de ground truth -- label provenance (STRONG vs. declarado)</h3>
        <LabelProvenanceSection
          datasetId={labelDatasetId} datasetVersion={labelDatasetVersion}
          setDatasetId={setLabelDatasetId} setDatasetVersion={setLabelDatasetVersion}
          report={labelReport} onLoad={loadLabelProvenance} loading={labelLoading}
        />
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-400">Canales / dias / receiver epochs</h3>
          <button type="button" onClick={loadEpochs} disabled={epochLoading} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10.5px] text-slate-300 hover:bg-slate-800 disabled:opacity-50">
            {epochLoading ? 'Actualizando…' : 'Refrescar'}
          </button>
        </div>
        {epochError && <NoDataNotice reason={epochError} />}
        {!epochError && <ReceiverEpochTable rows={epochRows} />}
      </section>
    </div>
  );
}
