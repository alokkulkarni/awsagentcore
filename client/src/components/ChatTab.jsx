import { useState, useRef, useEffect, useCallback } from 'react';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';

/**
 * Chat tab UI component.
 * @param {{ chat: object }} props
 */
export default function ChatTab({ chat }) {
  const { messages, isLoading, sendMessage, clearMessages, transferred } = chat;
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text || isLoading || transferred) return;
    setInputValue('');
    sendMessage(text);
  }, [inputValue, isLoading, sendMessage, transferred]);

  const handleKeyDown = (e) => {
    if (e.detail.key === 'Enter' && !e.detail.shiftKey) {
      handleSend();
    }
  };

  const formatTime = (iso) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  return (
    <div className="chat-container">
      {/* Messages area */}
      <div className="messages-area">
        {messages.length === 0 && !isLoading && (
          <div className="empty-state">
            <div className="empty-state-icon">💬</div>
            <div style={{ fontWeight: 600 }}>Start a conversation with ARIA</div>
            <div style={{ fontSize: '13px' }}>Your Adaptive Responsive Intelligence Agent</div>
          </div>
        )}

        {messages.map((msg) => {
          if (msg.role === 'transfer') {
            return (
              <div key={msg.id} className="message-row transfer">
                <div
                  className="message-bubble transfer"
                  style={{
                    background: '#0972d3',
                    color: '#fff',
                    borderRadius: '12px',
                    padding: '10px 16px',
                    maxWidth: '80%',
                    textAlign: 'center',
                    margin: '12px auto',
                  }}
                >
                  <div style={{ fontWeight: 700, marginBottom: '4px' }}>
                    🔄 Transferring to Specialist Team
                  </div>
                  <div style={{ fontSize: '13px', opacity: 0.9 }}>{msg.content}</div>
                </div>
                <div className="message-meta" style={{ textAlign: 'center', width: '100%' }}>
                  {formatTime(msg.timestamp)}
                </div>
              </div>
            );
          }

          return (
            <div key={msg.id} className={`message-row ${msg.role === 'user' ? 'user' : 'assistant'}`}>
              <div className={`message-bubble ${msg.role === 'user' ? 'user' : 'assistant'}`}>
                {msg.content.split('\n').map((line, i, arr) => (
                  line.trim() === '' ? (
                    i < arr.length - 1 ? <br key={i} /> : null
                  ) : (
                    <p key={i} style={{ margin: '0 0 4px 0' }}>{line}</p>
                  )
                ))}
              </div>
              <div className="message-meta">
                {msg.role === 'user' ? 'You' : 'ARIA'} · {formatTime(msg.timestamp)}
              </div>
            </div>
          );
        })}

        {isLoading && (
          <div className="message-row assistant">
            <div className="typing-indicator">
              <div className="typing-dot" />
              <div className="typing-dot" />
              <div className="typing-dot" />
            </div>
            <div className="message-meta">ARIA is thinking…</div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Transfer banner — shown when session has been handed off */}
      {transferred && (
        <div
          style={{
            background: '#f0f8ff',
            border: '1px solid #0972d3',
            borderRadius: '8px',
            padding: '10px 16px',
            margin: '8px 16px',
            fontSize: '13px',
            color: '#0972d3',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span style={{ fontSize: '16px' }}>🔒</span>
          <span>
            <strong>Session transferred.</strong> A specialist will continue this conversation.
            You can <button
              onClick={clearMessages}
              style={{
                background: 'none', border: 'none', color: '#0972d3',
                cursor: 'pointer', textDecoration: 'underline', padding: 0, font: 'inherit',
              }}
            >start a new chat</button> if you need further help.
          </span>
        </div>
      )}

      {/* Input area */}
      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <Input
            value={inputValue}
            onChange={({ detail }) => setInputValue(detail.value)}
            onKeyDown={handleKeyDown}
            placeholder={transferred ? 'Session transferred to specialist — start a new chat to continue' : 'Message ARIA…'}
            disabled={isLoading || transferred}
            autoFocus
          />
        </div>
        <SpaceBetween size="xs" direction="horizontal">
          <Button
            variant="primary"
            onClick={handleSend}
            disabled={!inputValue.trim() || isLoading || transferred}
            loading={isLoading}
          >
            Send
          </Button>
          <Button
            variant="normal"
            onClick={clearMessages}
            disabled={messages.length === 0}
          >
            Clear
          </Button>
        </SpaceBetween>
      </div>
    </div>
  );
}
