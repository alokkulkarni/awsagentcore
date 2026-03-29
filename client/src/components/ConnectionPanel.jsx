import { useState } from 'react';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import FormField from '@cloudscape-design/components/form-field';
import RadioGroup from '@cloudscape-design/components/radio-group';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Toggle from '@cloudscape-design/components/toggle';

/**
 * Collapsible connection configuration panel.
 * @param {{ connection: { config: object, updateConfig: function } }} props
 */
export default function ConnectionPanel({ connection }) {
  const { config, updateConfig } = connection;
  const [draft, setDraft] = useState({ ...config });

  const handleSave = () => {
    updateConfig(draft);
  };

  const handleReset = () => {
    setDraft({ ...config });
  };

  const update = (key, value) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="connection-panel">
      <SpaceBetween size="m">
        {/* Mode selector */}
        <FormField label="Connection Mode">
          <RadioGroup
            value={draft.mode}
            onChange={({ detail }) => update('mode', detail.value)}
            items={[
              { value: 'local', label: 'Local (direct HTTP/WS)' },
              { value: 'agentcore', label: 'AgentCore Runtime' },
            ]}
          />
        </FormField>

        {/* Local mode URLs */}
        {draft.mode === 'local' && (
          <SpaceBetween size="s" direction="horizontal">
            <FormField label="Chat URL" constraintText="e.g. http://localhost:8080">
              <Input
                value={draft.localChatUrl}
                onChange={({ detail }) => update('localChatUrl', detail.value)}
                placeholder="http://localhost:8080"
              />
            </FormField>
            <FormField label="WebSocket URL" constraintText="e.g. ws://localhost:8080/ws">
              <Input
                value={draft.localWsUrl}
                onChange={({ detail }) => update('localWsUrl', detail.value)}
                placeholder="ws://localhost:8080/ws"
              />
            </FormField>
          </SpaceBetween>
        )}

        {/* AgentCore mode URLs */}
        {draft.mode === 'agentcore' && (
          <SpaceBetween size="s" direction="horizontal">
            <FormField label="AgentCore Chat Endpoint" constraintText="Paste the /invocations URL from deploy output">
              <Input
                value={draft.agentcoreChatUrl}
                onChange={({ detail }) => update('agentcoreChatUrl', detail.value)}
                placeholder="https://…bedrock-agentcore.amazonaws.com/…"
              />
            </FormField>
            <FormField label="AgentCore WebSocket Endpoint">
              <Input
                value={draft.agentcoreWsUrl}
                onChange={({ detail }) => update('agentcoreWsUrl', detail.value)}
                placeholder="wss://…bedrock-agentcore.amazonaws.com/…"
              />
            </FormField>
          </SpaceBetween>
        )}

        {/* Authentication toggle + AWS credentials */}
        <ExpandableSection
          headerText="Authentication & AWS Credentials"
          expanded={draft.authenticated}
          onChange={({ detail }) => update('authenticated', detail.expanded)}
        >
          <SpaceBetween size="s">
            <Toggle
              checked={draft.authenticated}
              onChange={({ detail }) => update('authenticated', detail.checked)}
            >
              Enable SigV4 signing (AgentCore authenticated mode)
            </Toggle>

            <SpaceBetween size="s" direction="horizontal">
              <FormField label="AWS Region">
                <Input
                  value={draft.awsRegion}
                  onChange={({ detail }) => update('awsRegion', detail.value)}
                  placeholder="us-east-1"
                />
              </FormField>
              <FormField label="Access Key ID">
                <Input
                  value={draft.awsAccessKeyId}
                  onChange={({ detail }) => update('awsAccessKeyId', detail.value)}
                  placeholder="AKIA..."
                  type="password"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween size="s" direction="horizontal">
              <FormField label="Secret Access Key">
                <Input
                  value={draft.awsSecretAccessKey}
                  onChange={({ detail }) => update('awsSecretAccessKey', detail.value)}
                  placeholder="Secret access key"
                  type="password"
                />
              </FormField>
              <FormField label="Session Token (optional)">
                <Input
                  value={draft.awsSessionToken}
                  onChange={({ detail }) => update('awsSessionToken', detail.value)}
                  placeholder="Temporary session token"
                  type="password"
                />
              </FormField>
            </SpaceBetween>
          </SpaceBetween>
        </ExpandableSection>

        {/* Save / Reset */}
        <SpaceBetween size="s" direction="horizontal">
          <Button variant="primary" onClick={handleSave}>Save Settings</Button>
          <Button onClick={handleReset}>Reset</Button>
        </SpaceBetween>
      </SpaceBetween>
    </div>
  );
}
