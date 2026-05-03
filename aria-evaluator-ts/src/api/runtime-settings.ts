import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const SETTINGS_FILE = resolve(process.cwd(), 'data', 'runtime-settings.json');

export const EDITABLE_SETTING_KEYS = [
  'EVAL_PROVIDER_DEFAULT',

  'CONNECT_INSTANCE_ID',
  'CONNECT_REGION',
  'AWS_REGION',
  'CONNECT_CONTACT_FLOW',
  'CONNECT_CONTACT_FLOW_NAME',
  'CONNECT_WEBRTC_FLOW_ID',
  'CONNECT_WEBRTC_CONNECT_ATTEMPTS',
  'CONNECT_PHONE_NUMBER',

  'LEX_BOT_ID',
  'LEX_BOT_ALIAS_ID',
  'LEX_BOT_LOCALE_ID',
  'LEX_REGION',

  'AZURE_DIRECT_LINE_SECRET',
  'AZURE_DIRECT_LINE_ENDPOINT',
  'AZURE_DIRECT_LINE_USER_ID',

  'STRANDS_ENDPOINT',
  'STRANDS_METHOD',
  'STRANDS_AUTH_TYPE',
  'STRANDS_AUTH_BEARER',
  'STRANDS_SIGV4_REGION',
  'STRANDS_SIGV4_SERVICE',
  'STRANDS_MESSAGE_FIELD',
  'STRANDS_RESPONSE_FIELD',
  'STRANDS_HISTORY_FIELD',
  'STRANDS_SESSION_ID_FIELD',
  'STRANDS_HEADERS_JSON',

  'COPILOT_DIRECT_LINE_SECRET',
  'COPILOT_DIRECT_LINE_ENDPOINT',
  'COPILOT_DIRECT_LINE_USER_ID',

  'CUSTOM_CHAT_ENDPOINT',
  'CUSTOM_CHAT_METHOD',
  'CUSTOM_CHAT_AUTH_BEARER',
  'CUSTOM_CHAT_MESSAGE_FIELD',
  'CUSTOM_CHAT_RESPONSE_FIELD',
  'CUSTOM_CHAT_HEADERS_JSON',

  'CUSTOM_VOICE_PROTOCOL',
  'DEEPGRAM_VOICE_WS_URL',
  'DEEPGRAM_API_KEY',
  'DEEPGRAM_VOICE_SETTINGS_JSON',
  'CUSTOM_VOICE_WS_URL',
  'CUSTOM_VOICE_WS_AUTH_HEADER_NAME',
  'CUSTOM_VOICE_WS_AUTH_HEADER_VALUE',
  'CUSTOM_VOICE_WS_INIT_JSON',
  'CUSTOM_VOICE_WS_SEND_TEMPLATE',
  'CUSTOM_VOICE_WS_AGENT_EVENT_TYPES',
  'CUSTOM_VOICE_WS_MESSAGE_PATH',

  'EVAL_CUSTOMER_ID',
  'EVAL_CUSTOMER_NAME',
  'EVAL_RESPONSE_TIMEOUT_SECONDS',
  'VOICE_INITIAL_GREETING_TIMEOUT_MS',
  'VOICE_GREETING_FOLLOWUP_TIMEOUT_MS',
  'VOICE_PRE_SEND_DELAY_MS',
  'VOICE_PRE_SEND_GUARD_TIMEOUT_MS',
  'VOICE_TURN_SETTLE_TIMEOUT_MS',
  'VOICE_TURN_SETTLE_MAX_MS',
  'VOICE_MAX_CONSECUTIVE_SILENT_WAITS',
  'VOICE_SILENT_WAIT_FOLLOWUP_PROMPT',
] as const;

type EditableSettingKey = typeof EDITABLE_SETTING_KEYS[number];
type SettingsMap = Partial<Record<EditableSettingKey, string>>;

function readOverrides(): SettingsMap {
  if (!existsSync(SETTINGS_FILE)) return {};
  try {
    const parsed = JSON.parse(readFileSync(SETTINGS_FILE, 'utf-8')) as Record<string, unknown>;
    const out: SettingsMap = {};
    for (const key of EDITABLE_SETTING_KEYS) {
      const value = parsed[key];
      if (typeof value === 'string' && value.trim()) out[key] = value;
    }
    return out;
  } catch {
    return {};
  }
}

function writeOverrides(overrides: SettingsMap): void {
  mkdirSync(dirname(SETTINGS_FILE), { recursive: true });
  writeFileSync(SETTINGS_FILE, JSON.stringify(overrides, null, 2), 'utf-8');
}

export function getEffectiveSettings(): Record<EditableSettingKey, string> {
  const overrides = readOverrides();
  const effective = {} as Record<EditableSettingKey, string>;
  for (const key of EDITABLE_SETTING_KEYS) {
    effective[key] = overrides[key] ?? process.env[key] ?? '';
  }
  return effective;
}

export function getRuntimeSettingsEnv(): Record<string, string> {
  const effective = getEffectiveSettings();
  const out: Record<string, string> = {};
  for (const key of EDITABLE_SETTING_KEYS) {
    if (effective[key]) out[key] = effective[key];
  }
  return out;
}

export function saveSettings(partial: Record<string, unknown>): Record<EditableSettingKey, string> {
  const current = readOverrides();
  const next = { ...current };
  for (const key of EDITABLE_SETTING_KEYS) {
    if (!(key in partial)) continue;
    const raw = partial[key];
    const value = typeof raw === 'string' ? raw.trim() : '';
    if (!value) delete next[key];
    else next[key] = value;
  }
  writeOverrides(next);
  return getEffectiveSettings();
}
