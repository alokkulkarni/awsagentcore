import { useState, useRef, useEffect, useCallback } from 'react';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';

/**
 * Chat tab UI component.
 * @param {{ chat: object }} props
 */
export default function ChatTab({ chat }) {
  const { messages, isLoading, sendMessage, clearMessages } = chat;
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text || isLoading) return;
    setInputValue('');
    sendMessage(text);
  }, [inputValue, isLoading, sendMessage]);

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

        {messages.map((msg) => (
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
        ))}

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

      {/* Input area */}
      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <Input
            value={inputValue}
            onChange={({ detail }) => setInputValue(detail.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message ARIA…"
            disabled={isLoading}
            autoFocus
          />
        </div>
        <SpaceBetween size="xs" direction="horizontal">
          <Button
            variant="primary"
            onClick={handleSend}
            disabled={!inputValue.trim() || isLoading}
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
