# ARIA Banking Client

A React + Vite client application for **ARIA** (Adaptive Responsive Intelligence Agent) at Meridian Bank. Supports both text chat and real-time voice conversations with the ARIA backend, in both local development and AWS AgentCore Runtime modes.

---

## Prerequisites

- **Node.js 18+** and **npm 9+**
- ARIA backend running (locally or deployed to AWS AgentCore Runtime)

---

## Installation

```bash
cd /path/to/awsagentcore/client
npm install
```

---

## Development

```bash
npm run dev
```

Opens at [http://localhost:3000](http://localhost:3000).

---

## Build & Preview

```bash
npm run build    # Produces dist/
npm run preview  # Serves dist/ locally
```

---

## Configuration

### Option 1 — UI Connection Panel

Click the ⚙️ **Settings** button in the header to open the Connection Panel where you can configure all connection parameters. Settings are persisted to `localStorage` automatically.

### Option 2 — Environment Variables

Copy `.env.example` to `.env.local` and fill in the values:

```bash
cp .env.example .env.local
```

| Variable | Description | Default |
|---|---|---|
| `VITE_LOCAL_CHAT_URL` | Local backend chat URL | `http://localhost:8080` |
| `VITE_LOCAL_WS_URL` | Local backend WebSocket URL | `ws://localhost:8080/ws` |
| `VITE_AGENTCORE_CHAT_URL` | AgentCore /invocations endpoint | _(empty)_ |
| `VITE_AGENTCORE_WS_URL` | AgentCore WebSocket endpoint | _(empty)_ |
| `VITE_AWS_REGION` | AWS region for SigV4 signing | `us-east-1` |
| `VITE_AWS_ACCESS_KEY_ID` | AWS access key (authenticated mode) | _(empty)_ |
| `VITE_AWS_SECRET_ACCESS_KEY` | AWS secret key (authenticated mode) | _(empty)_ |
| `VITE_AWS_SESSION_TOKEN` | AWS session token (temporary creds) | _(empty)_ |

> ⚠️ **Never commit credentials to source control.** Use `.env.local` (git-ignored) or provide them at runtime through the UI.

---

## Usage Guide

### Chat Tab

1. Ensure your backend is running
2. In the header, verify the Customer ID (default `CUST-001`)
3. Type a message in the input field and press **Send** or hit **Enter**
4. ARIA's response appears in the conversation thread
5. Use **Clear** to reset the conversation

### Voice Tab

1. Click **Connect** — this opens the WebSocket connection to the backend
2. Once connected, press the 🎤 **microphone button** to start speaking
3. Speak your query; the waveform visualizer shows live audio levels
4. Press the 🎙️ button again to stop recording
5. ARIA's voice response plays back automatically
6. The transcript panel shows the full conversation in text
7. Click **Disconnect** to end the voice session

---

## Connection Modes

### Local Mode (default)

Used for local development when running the ARIA backend directly:

```
Chat:  POST http://localhost:8080/invocations
Voice: WebSocket ws://localhost:8080/ws
```

### AgentCore Mode

Used when ARIA is deployed to AWS Bedrock AgentCore Runtime. Paste the endpoints from your deploy output into the Connection Panel.

```
Chat:  POST https://<runtime-id>.bedrock-agentcore.amazonaws.com/.../invocations
Voice: WebSocket wss://<runtime-id>.bedrock-agentcore.amazonaws.com/...
```

---

## Authentication

When **Auth** is toggled on in the header (and AWS credentials are provided), the client automatically signs HTTP requests using **AWS Signature Version 4 (SigV4)** before sending them to the AgentCore endpoint.

1. Open the Connection Panel (⚙️ button)
2. Enable **Authentication & AWS Credentials**
3. Enter your AWS Region, Access Key ID, Secret Access Key, and optionally a Session Token
4. Click **Save Settings**
5. Enable the **Auth** toggle in the header

For production, use temporary credentials from AWS STS / IAM Identity Center rather than long-lived access keys.

---

## API Protocol

### Chat (HTTP)

```
POST /invocations
Content-Type: application/json

{"message": "...", "authenticated": true, "customer_id": "CUST-001"}

→ 200 OK: plain text (ARIA's response)
```

### Voice (WebSocket)

| Direction | Format | Description |
|---|---|---|
| Client → Server | JSON text | `{"type": "session.config", "authenticated": true, "customer_id": "CUST-001"}` |
| Client → Server | binary | Raw 16 kHz 16-bit mono PCM (1024 frames = 2048 bytes) |
| Client → Server | JSON text | `{"type": "session.end"}` |
| Server → Client | JSON text | `{"type": "session.started"}` / `{"type": "transcript.user", "text": "..."}` / etc. |
| Server → Client | binary | Raw 24 kHz 16-bit mono PCM (ARIA's voice) |

---

## Project Structure

```
client/
├── index.html
├── package.json
├── vite.config.js
├── .env.example
├── README.md
└── src/
    ├── main.jsx              # React entry point
    ├── App.jsx               # Root component (tabs, layout)
    ├── App.css               # Global styles (Meridian Bank theme)
    ├── hooks/
    │   ├── useConnection.js  # Config state + localStorage persistence
    │   ├── useChat.js        # HTTP chat logic
    │   └── useVoice.js       # WebSocket voice + audio logic
    ├── components/
    │   ├── Header.jsx        # Top navigation bar
    │   ├── ChatTab.jsx       # Chat conversation UI
    │   ├── VoiceTab.jsx      # Voice UI + waveform visualizer
    │   ├── ConnectionPanel.jsx # Settings panel
    │   └── StatusBadge.jsx   # Connection status indicator
    └── helpers/
        ├── audioCapture.js   # Web Audio capture + resampling
        ├── audioPlayer.js    # Gapless PCM playback
        └── agentcoreClient.js # HTTP client with SigV4 signing
```
