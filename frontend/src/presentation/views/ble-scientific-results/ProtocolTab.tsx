import { useState } from 'react';
import { AnalysisContract, BleScientificResultsApiService } from '../../../app/services/bleScientificResultsApi';

const api = new BleScientificResultsApiService();

const inputClass = 'w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none';
const labelClass = 'mb-1 block text-xs font-medium text-slate-400';

export default function ProtocolTab() {
  const [protocolId, setProtocolId] = useState('');
  const [hardwareProfileId, setHardwareProfileId] = useState('usrp-b200-e3r04z1b2');
  const [receiverProfileHash, setReceiverProfileHash] = useState('');
  const [interpretationMatrixHash, setInterpretationMatrixHash] = useState('');
  const [deviceIds, setDeviceIds] = useState('');
  const [channels, setChannels] = useState('37');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [frozen, setFrozen] = useState<AnalysisContract | null>(null);
  const [versions, setVersions] = useState<AnalysisContract[]>([]);

  const freeze = async () => {
    setBusy(true);
    setError(null);
    try {
      const contract = await api.freezeProtocol({
        protocol_id: protocolId.trim() || undefined,
        hardware_profile_id: hardwareProfileId.trim(),
        receiver_profile_hash: receiverProfileHash.trim(),
        interpretation_matrix_hash: interpretationMatrixHash.trim(),
        device_ids: deviceIds.split(',').map((v) => v.trim()).filter(Boolean),
        channels: channels.split(',').map((v) => Number(v.trim())).filter((v) => !Number.isNaN(v)),
      });
      setFrozen(contract);
      setProtocolId(contract.protocol_id);
      const history = await api.listProtocolVersions(contract.protocol_id);
      setVersions(history);
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'No se pudo congelar el protocolo.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 p-4">
      <div>
        <div className="text-sm font-semibold text-slate-200">Contrato de congelacion del experimento</div>
        <div className="mt-1 text-xs text-slate-500">
          Congela un <code>analysis_contract.json</code> inmutable. Una modificacion nunca sobrescribe una version existente
          -- siempre crea <code>protocol_version</code> + 1 bajo el mismo <code>protocol_id</code>.
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>protocol_id (vacio = nuevo protocolo)</label>
          <input className={inputClass} value={protocolId} onChange={(e) => setProtocolId(e.target.value)} placeholder="p.ej. BLE-PAPER-2026" />
        </div>
        <div>
          <label className={labelClass}>hardware_profile_id *</label>
          <input className={inputClass} value={hardwareProfileId} onChange={(e) => setHardwareProfileId(e.target.value)} />
        </div>
        <div>
          <label className={labelClass}>receiver_profile_hash *</label>
          <input className={inputClass} value={receiverProfileHash} onChange={(e) => setReceiverProfileHash(e.target.value)} placeholder="hash del perfil de receptor" />
        </div>
        <div>
          <label className={labelClass}>interpretation_matrix_hash *</label>
          <input className={inputClass} value={interpretationMatrixHash} onChange={(e) => setInterpretationMatrixHash(e.target.value)} placeholder="hash de la matriz de interpretacion predeclarada" />
        </div>
        <div>
          <label className={labelClass}>device_ids (separados por coma)</label>
          <input className={inputClass} value={deviceIds} onChange={(e) => setDeviceIds(e.target.value)} placeholder="CC2650-UNIT-01, SHELLY-PLUG-01" />
        </div>
        <div>
          <label className={labelClass}>channels (separados por coma)</label>
          <input className={inputClass} value={channels} onChange={(e) => setChannels(e.target.value)} placeholder="37, 38, 39" />
        </div>
      </div>

      <button
        className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={busy || !hardwareProfileId.trim() || !receiverProfileHash.trim() || !interpretationMatrixHash.trim()}
        onClick={freeze}
      >
        {busy ? 'Congelando...' : 'Congelar protocolo'}
      </button>

      {error && <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</div>}

      {frozen && (
        <div className="rounded border border-slate-700 bg-slate-900/60 p-3 text-xs text-slate-300">
          <div className="mb-2 text-sm font-semibold text-cyan-300">Protocolo congelado</div>
          <Row label="protocol_id" value={frozen.protocol_id} />
          <Row label="protocol_version" value={String(frozen.protocol_version)} />
          <Row label="git_commit" value={frozen.git_commit} />
          <Row label="git_dirty_state" value={frozen.git_dirty_state} />
          <Row label="creation_timestamp_utc" value={frozen.creation_timestamp_utc} />
          <Row label="association_policy_hash" value={frozen.association_policy_hash} />
          <Row label="quality_policy_hash" value={frozen.quality_policy_hash} />
          <Row label="dataset_policy_hash" value={frozen.dataset_policy_hash} />
        </div>
      )}

      {versions.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-400">Historial de versiones -- {frozen?.protocol_id}</div>
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="text-slate-500">
              <tr><th className="py-1 pr-3">version</th><th className="py-1 pr-3">creation_timestamp_utc</th><th className="py-1 pr-3">git_commit</th><th className="py-1">git_dirty_state</th></tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.protocol_version} className="border-t border-slate-800">
                  <td className="py-1 pr-3">{v.protocol_version}</td>
                  <td className="py-1 pr-3">{v.creation_timestamp_utc}</td>
                  <td className="py-1 pr-3">{v.git_commit.slice(0, 12)}</td>
                  <td className="py-1">{v.git_dirty_state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-t border-slate-800 py-1 first:border-t-0">
      <span className="text-slate-500">{label}</span>
      <span className="truncate font-mono text-slate-200">{value}</span>
    </div>
  );
}
