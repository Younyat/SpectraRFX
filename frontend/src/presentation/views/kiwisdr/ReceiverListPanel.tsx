import { RadioTower } from 'lucide-react';
import type { Receiver } from '../../../domain/kiwisdr/Receiver';
import { cn } from '../../../shared/utils';

export function ReceiverListPanel({
  receivers,
  selectedId,
  onSelect,
}: {
  receivers: Receiver[];
  selectedId: string | null;
  onSelect: (receiver: Receiver) => void;
}) {
  return (
    <aside className="min-h-0 w-[360px] border-r border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="text-sm font-semibold text-slate-100">{receivers.length} receivers</div>
        <div className="text-xs text-slate-400">Backend catalog, cached locally</div>
      </div>
      <div className="h-full overflow-auto pb-20">
        {receivers.map((receiver) => (
          <button
            key={receiver.id}
            onClick={() => onSelect(receiver)}
            className={cn(
              'block w-full border-b border-slate-800 px-4 py-3 text-left hover:bg-slate-800',
              selectedId === receiver.id && 'bg-cyan-950/70'
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-100">{receiver.name}</div>
                <div className="mt-1 truncate text-xs text-slate-400">{receiver.host}:{receiver.port}</div>
              </div>
              <RadioTower className={cn('h-4 w-4 shrink-0', receiver.is_online ? 'text-emerald-300' : 'text-red-300')} />
            </div>
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-300">
              <span>{receiver.country || 'Unknown region'}</span>
              {receiver.current_users !== null && receiver.max_users !== null && (
                <span>{receiver.current_users}/{receiver.max_users} users</span>
              )}
              {receiver.snr !== null && <span>SNR {receiver.snr} dB</span>}
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
