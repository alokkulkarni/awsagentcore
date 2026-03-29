import StatusIndicator from '@cloudscape-design/components/status-indicator';

/**
 * Displays a Cloudscape StatusIndicator reflecting the current voice/connection status.
 * @param {{ status: string }} props
 */
export default function StatusBadge({ status }) {
  const statusMap = {
    connected: { type: 'success', label: 'Connected' },
    connecting: { type: 'pending', label: 'Connecting...' },
    idle: { type: 'stopped', label: 'Disconnected' },
    listening: { type: 'in-progress', label: 'Listening' },
    'aria-speaking': { type: 'info', label: 'ARIA Speaking' },
    error: { type: 'error', label: 'Error' },
  };

  const { type, label } = statusMap[status] || { type: 'stopped', label: 'Disconnected' };

  return (
    <div className="status-badge-wrapper">
      <StatusIndicator type={type}>{label}</StatusIndicator>
    </div>
  );
}
