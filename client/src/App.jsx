import { useState, useEffect } from 'react';
import { Amplify } from 'aws-amplify';
import Tabs from '@cloudscape-design/components/tabs';
import './App.css';
import { useConnection } from './hooks/useConnection.js';
import { useChat } from './hooks/useChat.js';
import { useVoice } from './hooks/useVoice.js';
import Header from './components/Header.jsx';
import ConnectionPanel from './components/ConnectionPanel.jsx';
import ChatTab from './components/ChatTab.jsx';
import VoiceTab from './components/VoiceTab.jsx';

function configureAmplify(config) {
  if (config.cognitoIdentityPoolId) {
    Amplify.configure({
      Auth: {
        Cognito: {
          identityPoolId: config.cognitoIdentityPoolId,
          allowGuestAccess: true,
        },
      },
    });
  }
}

export default function App() {
  const connection = useConnection();
  const [activeTab, setActiveTab] = useState('chat');
  const [showConnectionPanel, setShowConnectionPanel] = useState(false);

  const chat = useChat(connection);
  const voice = useVoice(connection);

  // Configure Amplify whenever Cognito identity pool ID changes
  useEffect(() => {
    configureAmplify(connection.config);
  }, [connection.config.cognitoIdentityPoolId]);

  return (
    <div className="app">
      <Header
        connection={connection}
        chatSessionId={chat.sessionId}
        voiceStatus={voice.status}
        onToggleConnectionPanel={() => setShowConnectionPanel((p) => !p)}
      />

      {showConnectionPanel && <ConnectionPanel connection={connection} />}

      <main className="app-content">
        <Tabs
          className="app-tabs"
          activeTabId={activeTab}
          onChange={({ detail }) => setActiveTab(detail.activeTabId)}
          fitHeight
          tabs={[
            {
              id: 'chat',
              label: '💬 Chat',
              content: <ChatTab chat={chat} />,
            },
            {
              id: 'voice',
              label: '🎙️ Voice',
              content: <VoiceTab voice={voice} />,
            },
          ]}
          variant="default"
        />
      </main>
    </div>
  );
}
