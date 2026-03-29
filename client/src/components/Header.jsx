import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Toggle from '@cloudscape-design/components/toggle';
import StatusBadge from './StatusBadge.jsx';

/**
 * App header bar.
 * @param {{
 *   connection: { config: object, updateConfig: function },
 *   chatSessionId: string,
 *   voiceStatus: string,
 *   onToggleConnectionPanel: function
 * }} props
 */
export default function Header({ connection, chatSessionId, voiceStatus, onToggleConnectionPanel }) {
  const { config, updateConfig } = connection;

  return (
    <header className="app-header">
      {/* Logo */}
      <div className="header-logo">
        🏦 ARIA
        <span className="bank-name">| Meridian Bank</span>
      </div>

      {/* Center controls */}
      <div className="header-center">
        {/* Mode badge */}
        <span style={{ color: '#00bcd4', fontSize: '12px', textTransform: 'uppercase', fontWeight: 600 }}>
          {config.mode === 'local' ? 'Local' : 'AgentCore'}
        </span>

        {/* Customer ID */}
        <div className="header-customer-id">
          <span>Customer:</span>
          <input
            value={config.customerId}
            onChange={(e) => updateConfig({ customerId: e.target.value })}
            aria-label="Customer ID"
          />
        </div>

        {/* Auth toggle */}
        <Toggle
          checked={config.authenticated}
          onChange={({ detail }) => updateConfig({ authenticated: detail.checked })}
        >
          <span style={{ color: '#d5dbdb', fontSize: '12px' }}>Auth</span>
        </Toggle>
      </div>

      {/* Right side */}
      <div className="header-right">
        <div className="session-id-display" title="Chat session ID">
          {chatSessionId ? `Session: ${chatSessionId.slice(0, 8)}…` : ''}
        </div>

        <StatusBadge status={voiceStatus} />

        <Button
          variant="icon"
          iconName="settings"
          onClick={onToggleConnectionPanel}
          ariaLabel="Toggle connection settings"
        />
      </div>
    </header>
  );
}
