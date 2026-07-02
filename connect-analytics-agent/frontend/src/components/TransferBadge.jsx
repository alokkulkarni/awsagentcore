/**
 * TransferBadge — shows whether a TRANSFER contact was sent to an internal
 * destination (queue / agent) or an external phone number, and reveals the
 * resolved destination on click.
 *
 * Backend source of truth: agent/eventbridge_listener.py `_classify_transfer()`
 * populates transferDirection / transferTargetType / transferTargetLabel on
 * every live contact of contactType "transfer". This component only renders
 * for those contacts and is otherwise a no-op (returns null).
 */
import { useEffect, useRef, useState } from 'react';
import { Building2, Globe, Loader2, User as UserIcon } from 'lucide-react';

const TARGET_TYPE_LABEL = {
  queue: 'Queue',
  agent: 'Agent',
  phone: 'External Number',
};

function badgeStyle(direction) {
  switch (direction) {
    case 'internal': return 'bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25';
    case 'external': return 'bg-orange-500/15 text-orange-400 hover:bg-orange-500/25';
    default:         return 'bg-slate-200/60 dark:bg-slate-700/60 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700';
  }
}

function badgeIcon(direction, targetType) {
  if (direction === 'external') return <Globe size={10} />;
  if (direction === 'internal') return targetType === 'agent' ? <UserIcon size={10} /> : <Building2 size={10} />;
  return <Loader2 size={10} className="animate-spin" />;
}

export default function TransferBadge({ contact }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onOutside = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onOutside);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onOutside);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (contact.contactType !== 'transfer') return null;

  const direction = contact.transferDirection || 'pending';
  const targetType = contact.transferTargetType;
  const label = contact.transferTargetLabel;
  const badgeText = direction === 'internal' ? 'Internal' : direction === 'external' ? 'External' : 'Transfer';

  return (
    <span ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        title="Click to see transfer destination"
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition ${badgeStyle(direction)}`}
      >
        {badgeIcon(direction, targetType)}
        {badgeText}
      </button>

      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute left-0 top-full z-20 mt-1 w-56 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3 text-left shadow-2xl"
        >
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-500">
            Transfer Destination
          </p>
          <dl className="space-y-1.5 text-xs">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-slate-600 dark:text-slate-500">Direction</dt>
              <dd className={direction === 'external' ? 'text-orange-600 dark:text-orange-400' : direction === 'internal' ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500 dark:text-slate-400'}>
                {direction === 'pending' ? 'Resolving…' : badgeText}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-slate-600 dark:text-slate-500">Target Type</dt>
              <dd className="text-slate-700 dark:text-slate-300">{TARGET_TYPE_LABEL[targetType] || '—'}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-slate-600 dark:text-slate-500">Destination</dt>
              <dd className="font-mono text-slate-800 dark:text-slate-200">{label || 'Resolving…'}</dd>
            </div>
          </dl>
          {direction === 'pending' && (
            <p className="mt-2 text-[10px] text-slate-600 dark:text-slate-500">
              Not enough routing info yet — this updates automatically as the transfer proceeds.
            </p>
          )}
        </div>
      )}
    </span>
  );
}
