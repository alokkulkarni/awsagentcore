import { useState } from 'react';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import FormField from '@cloudscape-design/components/form-field';
import RadioGroup from '@cloudscape-design/components/radio-group';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Toggle from '@cloudscape-design/components/toggle';
import { getAgentcoreVoiceWssBase } from '../hooks/useConnection';

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

  const computedWssBase = getAgentcoreVoiceWssBase(draft);

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
                value={draft.localVoiceUrl}
                onChange={({ detail }) => update('localVoiceUrl', detail.value)}
                placeholder="ws://localhost:8080/ws"
              />
            </FormField>
          </SpaceBetween>
        )}

        {/* AgentCore mode */}
        {draft.mode === 'agentcore' && (
          <SpaceBetween size="s">
            <FormField label="AgentCore Chat Endpoint" constraintText="Paste the /invocations URL from deploy output">
              <Input
                value={draft.agentcoreChatUrl}
                onChange={({ detail }) => update('agentcoreChatUrl', detail.value)}
                placeholder="https://bedrock-agentcore.eu-west-2.amazonaws.com/runtimes/…/invocations"
              />
            </FormField>
            <FormField
              label="AgentCore Runtime ID"
              constraintText="e.g. aria_banking_agent-RhdjurH3YC — from deploy output or AgentCore console"
            >
              <Input
                value={draft.agentcoreRuntimeId}
                onChange={({ detail }) => update('agentcoreRuntimeId', detail.value)}
                placeholder="aria_banking_agent-RhdjurH3YC"
              />
            </FormField>
            {computedWssBase && (
              <FormField
                label="Voice WebSocket URL (computed)"
                constraintText="Read-only — generated from Runtime ID + region. Voice uses SigV4 presigned URL derived from your Cognito credentials."
              >
                <Input value={computedWssBase} readOnly />
              </FormField>
            )}
          </SpaceBetween>
        )}

        {/* Authentication toggle + Cognito credentials */}
        <ExpandableSection
          headerText="Authentication (Cognito Identity Pool)"
          expanded={draft.authenticated}
          onChange={({ detail }) => update('authenticated', detail.expanded)}
        >
          <SpaceBetween size="s">
            <Toggle
              checked={draft.authenticated}
              onChange={({ detail }) => update('authenticated', detail.checked)}
            >
              Enable SigV4 signing via Cognito Identity Pool
            </Toggle>

            <p style={{ margin: 0, color: '#5f6b7a', fontSize: '0.875rem' }}>
              Cognito Identity Pool provides temporary AWS credentials automatically — no long-term keys needed.
            </p>

            <SpaceBetween size="s" direction="horizontal">
              <FormField
                label="Cognito Identity Pool ID"
                constraintText="e.g. eu-west-2:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              >
                <Input
                  value={draft.cognitoIdentityPoolId}
                  onChange={({ detail }) => update('cognitoIdentityPoolId', detail.value)}
                  placeholder="eu-west-2:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                />
              </FormField>
              <FormField label="AWS Region">
                <Input
                  value={draft.awsRegion}
                  onChange={({ detail }) => update('awsRegion', detail.value)}
                  placeholder="eu-west-2"
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
