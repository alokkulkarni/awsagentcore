# Brainstorming Agent

A full-stack brainstorming workspace built with FastAPI, Strands agents, SQLite memory, WebSockets, and a React + Vite + Tailwind UI. It supports persistent idea capture, session-based thinking, real-time streaming, and browser-native voice input/output.

## What it is

This app gives you a strategic brainstorming copilot powered by Amazon Bedrock (`eu.anthropic.claude-sonnet-4-6` by default). It keeps conversation context inside each session, saves high-value insights into SQLite, and lets you search, filter, and revisit connected ideas later.

## Features

- FastAPI backend with Strands agent tools
- SQLite-backed memory with sessions, saved insights, and links between ideas
- WebSocket streaming for live agent responses and tool activity updates
- React + Vite frontend with a dark slate workspace
- Session manager for starting and switching brainstorming threads
- Memory browser with topic filters, search, and related-idea expansion
- Browser voice support using Web Speech API
- Configurable Bedrock model through `BEDROCK_MODEL_ID`
- Dockerised frontend and backend for quick local startup

## Quick start

1. Create an environment file:

   ```bash
   cd brainstorming-agent
   cp .env.example .env
   ```

2. Fill in your AWS credentials and region in `.env`.

3. Start the stack:

   ```bash
   cd docker
   docker compose --env-file ../.env up --build
   ```

4. Open:

   - Frontend: `http://localhost:5175`
   - Backend health check: `http://localhost:8200/health`

## Voice usage

Voice mode uses browser-native APIs only:

- **SpeechRecognition** for speech-to-text
- **SpeechSynthesis** for text-to-speech

For the best experience use Chrome or Edge and allow microphone access when prompted. If the browser does not support Web Speech API, the app falls back gracefully and keeps chat fully usable.

## Memory system

The backend stores three things in SQLite:

- **sessions**: brainstorming threads with title, topics, timestamps, and summary
- **memories**: individual insights or decisions saved by the agent
- **memory links**: relationships between related ideas

Full-text search is powered by SQLite FTS5. The agent can save ideas, search old insights, pull memories by topic, and link connected concepts while brainstorming.

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `AWS_ACCESS_KEY_ID` | Yes | - | AWS access key for Bedrock |
| `AWS_SECRET_ACCESS_KEY` | Yes | - | AWS secret key for Bedrock |
| `AWS_SESSION_TOKEN` | No | empty | Optional session token for SSO or temporary creds |
| `AWS_REGION` | No | `eu-west-1` | AWS region used by Bedrock |
| `BEDROCK_MODEL_ID` | No | `eu.anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `DB_PATH` | No | `agent/data/brainstorm.db` | SQLite database path inside the backend container/app |

## Project structure

```text
brainstorming-agent/
├── agent/          # FastAPI + Strands + SQLite
├── frontend/       # React + Vite + Tailwind UI
└── docker/         # Dockerfiles, compose, nginx proxy
```

## Local development

Backend:

```bash
cd brainstorming-agent/agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8200
```

Frontend:

```bash
cd brainstorming-agent/frontend
npm install
npm run dev
```

The Vite dev server listens on port `5175`.
