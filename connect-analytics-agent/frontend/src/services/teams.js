/**
 * Microsoft Teams provider for the in-dashboard Teams panel.
 *
 * Teams cannot be iframed (unlike the Connect CCP), so the panel renders its
 * own surface from Microsoft's APIs. Provider selection at runtime:
 *   - Mock       — dashboard mock mode ON: simulated chats + presence, zero
 *                  Microsoft network calls. Fully interactive for demos.
 *   - Graph      — VITE_TEAMS_CLIENT_ID + VITE_TEAMS_TENANT_ID set: MSAL popup
 *                  sign-in (delegated), Microsoft Graph for chat + presence.
 *   - Unconfigured — real mode without Entra IDs: panel shows setup steps.
 *
 * Delegated-only by design: no app secrets, tokens stay in the browser, and
 * no Teams content ever reaches the dashboard backend.
 */

import { getConfig, getTeamsConfig } from './api';

const CLIENT_ID = import.meta.env.VITE_TEAMS_CLIENT_ID || '';
const TENANT_ID = import.meta.env.VITE_TEAMS_TENANT_ID || '';
const GRAPH_SCOPES = ['User.Read', 'Chat.ReadWrite', 'Presence.Read.All'];
const GRAPH = 'https://graph.microsoft.com/v1.0';

// Teams-style presence, keyed the way Graph reports availability
export const PRESENCE_STYLE = {
  Available:    { colour: '#22c55e', label: 'Available' },
  Busy:         { colour: '#ef4444', label: 'Busy' },
  DoNotDisturb: { colour: '#b91c1c', label: 'Do not disturb' },
  Away:         { colour: '#f59e0b', label: 'Away' },
  BeRightBack:  { colour: '#f59e0b', label: 'Be right back' },
  Offline:      { colour: '#94a3b8', label: 'Offline' },
};

export function teamsDeepLink(email) {
  return `https://teams.microsoft.com/l/chat/0/0?users=${encodeURIComponent(email)}`;
}

// ── Mock provider ──────────────────────────────────────────────────────────────

const MOCK_REPLIES = [
  'On it — wrapping this call now.',
  'Thanks for the heads up 👍',
  'Can you send the contact ID?',
  'Taking my break in 5, back shortly.',
  'Escalating that one to fraud team.',
];

function relTime(secondsAgo) {
  return new Date(Date.now() - secondsAgo * 1000).toISOString();
}

class MockTeamsProvider {
  constructor() {
    this.kind = 'mock';
    this.account = { name: 'You (Supervisor)', username: 'supervisor@contoso-demo.com' };
    this.chats = [
      {
        id: 'chat-1', topic: 'Sarah Johnson', unread: 1,
        messages: [
          { id: 'm1', from: 'Sarah Johnson', mine: false, at: relTime(50 * 60), text: 'Morning! Queue looks heavy today.' },
          { id: 'm2', from: 'You', mine: true, at: relTime(48 * 60), text: 'Yes — keep an eye on Mortgages (UK) please.' },
          { id: 'm3', from: 'Sarah Johnson', mine: false, at: relTime(6 * 60), text: 'Long caller on my line wants a callback booked instead.' },
        ],
      },
      {
        id: 'chat-2', topic: 'Marcus Lee', unread: 1,
        messages: [
          { id: 'm4', from: 'Marcus Lee', mine: false, at: relTime(14 * 60), text: 'System keeps dropping me to ACW — anyone else?' },
        ],
      },
      {
        id: 'chat-3', topic: 'Contact Centre Leads', unread: 0, group: true,
        messages: [
          { id: 'm5', from: 'Priya Sharma', mine: false, at: relTime(3 * 3600), text: 'Reminder: shift handover notes by 5pm.' },
          { id: 'm6', from: 'You', mine: true, at: relTime(2.5 * 3600), text: 'Will do — adding callback stats this week.' },
        ],
      },
    ];
    this._replyTimers = [];
    this._lastInboundAt = Date.now();
  }

  async getState() { return { status: 'ready', account: this.account, mock: true }; }
  async signIn() { return this.getState(); }
  async signOut() { /* mock stays signed in */ }

  // Occasionally deliver a simulated inbound message so the badge feels live
  _maybeSimulateInbound() {
    if (Date.now() - this._lastInboundAt < 90_000) return;
    this._lastInboundAt = Date.now();
    const chat = this.chats[Math.floor(Math.random() * this.chats.length)];
    chat.messages.push({
      id: `m${Date.now()}`, from: chat.group ? 'Priya Sharma' : chat.topic,
      mine: false, at: new Date().toISOString(),
      text: MOCK_REPLIES[Math.floor(Math.random() * MOCK_REPLIES.length)],
    });
    chat.unread += 1;
  }

  async listChats() {
    this._maybeSimulateInbound();
    return this.chats.map((c) => ({
      id: c.id, topic: c.topic, group: !!c.group, unread: c.unread,
      last: c.messages[c.messages.length - 1] || null,
    }));
  }

  async listMessages(chatId) {
    const chat = this.chats.find((c) => c.id === chatId);
    if (chat) chat.unread = 0;
    return chat ? [...chat.messages] : [];
  }

  async sendMessage(chatId, text) {
    const chat = this.chats.find((c) => c.id === chatId);
    if (!chat) return;
    chat.messages.push({ id: `m${Date.now()}`, from: 'You', mine: true, at: new Date().toISOString(), text });
    const timer = setTimeout(() => {
      chat.messages.push({
        id: `m${Date.now()}r`, from: chat.group ? 'Priya Sharma' : chat.topic, mine: false,
        at: new Date().toISOString(),
        text: MOCK_REPLIES[Math.floor(Math.random() * MOCK_REPLIES.length)],
      });
    }, 4000);
    this._replyTimers.push(timer);
  }

  async unreadCount() {
    this._maybeSimulateInbound();
    return this.chats.reduce((n, c) => n + c.unread, 0);
  }

  /** Find or create the 1:1 chat with a person — used by the roster chat button. */
  async openChatWith({ name }) {
    let chat = this.chats.find((c) => !c.group && c.topic === name);
    if (!chat) {
      chat = { id: `chat-${name.toLowerCase().replace(/[^a-z]+/g, '-')}`, topic: name, unread: 0, messages: [] };
      this.chats.unshift(chat);
    }
    return { id: chat.id, topic: chat.topic, group: false };
  }

  /**
   * Mock presence coheres with what the roster already shows: an agent the
   * dashboard says is On Call reads as Busy in Teams, and so on.
   */
  async getPresence(agents) {
    const map = {};
    for (const a of agents) {
      const s = a.hint || '';
      map[a.key] =
        s === 'On Call' ? (a.key.length % 3 === 0 ? 'DoNotDisturb' : 'Busy')
        : s === 'Available' ? 'Available'
        : s === 'After Contact Work' ? 'Busy'
        : s === 'Non-Productive' ? 'Away'
        : s === 'Offline' ? 'Offline'
        : 'Available';
    }
    return map;
  }
}

// ── Graph provider (real mode, env-gated) ──────────────────────────────────────

const READ_STATE_KEY = 'connect.analytics.teams.readState';

function loadReadState() {
  try { return JSON.parse(localStorage.getItem(READ_STATE_KEY) || '{}'); } catch { return {}; }
}

class GraphTeamsProvider {
  constructor(clientId = CLIENT_ID, tenantId = TENANT_ID) {
    this.kind = 'graph';
    this._clientId = clientId;
    this._tenantId = tenantId;
    this._msal = null;
    this._account = null;
    this._userIdCache = new Map(); // email → AAD object id (null = not found)
    this._readState = loadReadState(); // chatId → ISO of last read message
    this._lastChats = [];
    this._presenceDeniedWarned = false;
  }

  _saveReadState() {
    try { localStorage.setItem(READ_STATE_KEY, JSON.stringify(this._readState)); } catch { /* quota — ignore */ }
  }

  async _instance() {
    if (this._msal) return this._msal;
    const { PublicClientApplication } = await import('@azure/msal-browser');
    this._msal = new PublicClientApplication({
      auth: {
        clientId: this._clientId,
        authority: `https://login.microsoftonline.com/${this._tenantId}`,
        redirectUri: window.location.origin,
      },
      cache: { cacheLocation: 'sessionStorage' },
    });
    await this._msal.initialize();
    const accounts = this._msal.getAllAccounts();
    if (accounts.length) this._account = accounts[0];
    return this._msal;
  }

  async getState() {
    await this._instance();
    const ids = { clientId: this._clientId, tenantId: this._tenantId };
    return this._account
      ? { status: 'ready', account: { name: this._account.name, username: this._account.username }, mock: false, ...ids }
      : { status: 'signed_out', mock: false, ...ids };
  }

  async signIn() {
    const msal = await this._instance();
    const result = await msal.loginPopup({ scopes: GRAPH_SCOPES });
    this._account = result.account;
    return this.getState();
  }

  async signOut() {
    const msal = await this._instance();
    await msal.logoutPopup({ account: this._account }).catch(() => {});
    this._account = null;
  }

  async _token() {
    const msal = await this._instance();
    if (!this._account) throw new Error('Not signed in to Microsoft 365');
    try {
      const r = await msal.acquireTokenSilent({ scopes: GRAPH_SCOPES, account: this._account });
      return r.accessToken;
    } catch {
      const r = await msal.acquireTokenPopup({ scopes: GRAPH_SCOPES });
      return r.accessToken;
    }
  }

  async _graph(path, options = {}, attempt = 0) {
    const token = await this._token();
    const resp = await fetch(`${GRAPH}${path}`, {
      ...options,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    // Graph throttling: honour Retry-After, retry twice before surfacing
    if (resp.status === 429 && attempt < 2) {
      const wait = Math.min(Number(resp.headers.get('Retry-After') || 2), 15);
      await new Promise((r) => setTimeout(r, wait * 1000));
      return this._graph(path, options, attempt + 1);
    }
    // Expired/invalidated token: force one refresh cycle then retry
    if (resp.status === 401 && attempt < 1) {
      const msal = await this._instance();
      await msal.acquireTokenPopup({ scopes: GRAPH_SCOPES }).then((r) => { this._account = r.account; }).catch(() => {});
      return this._graph(path, options, attempt + 1);
    }
    if (!resp.ok) {
      const err = new Error(`Graph ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
      err.status = resp.status;
      throw err;
    }
    return resp.status === 204 ? null : resp.json();
  }

  _chatTopic(chat) {
    if (chat.topic) return chat.topic;
    const others = (chat.members || []).filter((m) => m.email !== this._account?.username);
    return others.map((m) => m.displayName).filter(Boolean).join(', ') || 'Chat';
  }

  async listChats() {
    const data = await this._graph('/me/chats?$expand=members,lastMessagePreview&$top=20&$orderby=lastMessagePreview/createdDateTime desc');
    this._lastChats = (data.value || []).map((c) => {
      const last = c.lastMessagePreview || null;
      const lastAt = last?.createdDateTime || null;
      const lastMine = last?.from?.user?.id === this._account?.localAccountId;
      // Graph exposes no unread count — track read state locally per chat
      const readUpTo = this._readState[c.id];
      const unread = lastAt && !lastMine && (!readUpTo || lastAt > readUpTo) ? 1 : 0;
      return {
        id: c.id,
        topic: this._chatTopic(c),
        group: c.chatType === 'group',
        unread,
        last: last ? {
          from: last.from?.user?.displayName || '',
          mine: lastMine,
          text: (last.body?.content || '').replace(/<[^>]+>/g, '').slice(0, 120),
          at: lastAt,
        } : null,
      };
    });
    return this._lastChats;
  }

  async listMessages(chatId) {
    const data = await this._graph(`/me/chats/${encodeURIComponent(chatId)}/messages?$top=30`);
    const messages = (data.value || [])
      .filter((m) => m.messageType === 'message')
      .map((m) => ({
        id: m.id,
        from: m.from?.user?.displayName || 'Unknown',
        mine: m.from?.user?.id === this._account?.localAccountId,
        at: m.createdDateTime,
        text: (m.body?.content || '').replace(/<[^>]+>/g, ''),
      }))
      .reverse();
    // Opening (or refreshing) a thread marks it read up to its newest message
    const newest = messages[messages.length - 1];
    if (newest?.at && (this._readState[chatId] || '') < newest.at) {
      this._readState[chatId] = newest.at;
      this._saveReadState();
      const cached = this._lastChats.find((c) => c.id === chatId);
      if (cached) cached.unread = 0;
    }
    return messages;
  }

  async sendMessage(chatId, text) {
    await this._graph(`/chats/${encodeURIComponent(chatId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ body: { content: text } }),
    });
  }

  async unreadCount() {
    return this._lastChats.reduce((n, c) => n + (c.unread || 0), 0);
  }

  /** Find (or create via Graph) the 1:1 chat with an agent's M365 account. */
  async openChatWith({ name, email }) {
    if (!email) {
      throw new Error(
        `No Microsoft 365 address is known for ${name || 'this agent'} yet — the agent→M365 mapping arrives in Phase 2.`,
      );
    }
    const chats = await this._graph("/me/chats?$expand=members&$filter=chatType eq 'oneOnOne'&$top=50");
    const existing = (chats.value || []).find((c) =>
      (c.members || []).some((m) => (m.email || '').toLowerCase() === email.toLowerCase()),
    );
    if (existing) return { id: existing.id, topic: name || email, group: false };

    const user = await this._graph(`/users/${encodeURIComponent(email)}?$select=id`);
    const created = await this._graph('/chats', {
      method: 'POST',
      body: JSON.stringify({
        chatType: 'oneOnOne',
        members: [this._account.localAccountId, user.id].map((id) => ({
          '@odata.type': '#microsoft.graph.aadUserConversationMember',
          roles: ['owner'],
          'user@odata.bind': `https://graph.microsoft.com/v1.0/users('${id}')`,
        })),
      }),
    });
    return { id: created.id, topic: name || email, group: false };
  }

  async getPresence(agents) {
    // Resolve agent emails to AAD ids (cached), then batch-fetch presence.
    const ids = [];
    const idToKey = {};
    for (const a of agents) {
      if (!a.email || !a.email.includes('@')) continue;
      if (!this._userIdCache.has(a.email)) {
        try {
          const u = await this._graph(`/users/${encodeURIComponent(a.email)}?$select=id`);
          this._userIdCache.set(a.email, u.id);
        } catch {
          this._userIdCache.set(a.email, null);
        }
      }
      const id = this._userIdCache.get(a.email);
      if (id) { ids.push(id); idToKey[id] = a.key; }
    }
    if (!ids.length) return {};
    try {
      const data = await this._graph('/communications/getPresencesByUserId', {
        method: 'POST',
        body: JSON.stringify({ ids: ids.slice(0, 650) }),
      });
      const map = {};
      for (const p of data.value || []) {
        const key = idToKey[p.id];
        if (key) map[key] = p.availability || 'Offline';
      }
      return map;
    } catch (e) {
      // Presence.Read.All needs admin consent — degrade to no dots, not errors
      if (e.status === 403 && !this._presenceDeniedWarned) {
        this._presenceDeniedWarned = true;
        console.warn('Teams presence unavailable: Presence.Read.All not consented for this app registration.');
      }
      if (e.status === 403) return {};
      throw e;
    }
  }
}

// ── Provider selection ─────────────────────────────────────────────────────────

let _provider = null;
let _providerPromise = null;

export async function getTeamsProvider() {
  if (_provider) return _provider;
  if (!_providerPromise) {
    _providerPromise = (async () => {
      let mockMode = false;
      try {
        const cfg = await getConfig();
        mockMode = !!cfg.mock_mode;
      } catch { /* backend unreachable — fall through on env config */ }

      // Entra IDs come from the backend at runtime (TEAMS_CLIENT_ID /
      // TEAMS_TENANT_ID env → /config/teams — no frontend rebuild needed),
      // with build-time VITE_ vars as a fallback.
      let clientId = CLIENT_ID;
      let tenantId = TENANT_ID;
      if (!mockMode) {
        try {
          const tc = await getTeamsConfig();
          if (tc.enabled) {
            clientId = tc.client_id;
            tenantId = tc.tenant_id;
          }
        } catch { /* older backend without /config/teams — env fallback */ }
      }

      if (mockMode) {
        _provider = new MockTeamsProvider();
      } else if (clientId && tenantId) {
        // Deliberately loud: makes stale-tab / stale-config debugging trivial
        console.info(`[teams] Graph provider — app ${clientId.slice(0, 8)}… tenant ${tenantId.slice(0, 8)}…`);
        _provider = new GraphTeamsProvider(clientId, tenantId);
      } else {
        _provider = {
          kind: 'unconfigured',
          async getState() { return { status: 'unconfigured', mock: false }; },
          async unreadCount() { return 0; },
          async getPresence() { return {}; },
        };
      }
      return _provider;
    })();
  }
  return _providerPromise;
}

/** Force re-selection (e.g. after the Dummy Data toggle changes). */
export function resetTeamsProvider() {
  _provider = null;
  _providerPromise = null;
}
