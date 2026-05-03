import { Router } from 'express';
import {
  EDITABLE_SETTING_KEYS,
  getEffectiveSettings,
  saveSettings,
} from '../runtime-settings.js';

export const settingsRouter = Router();

settingsRouter.get('/', (_req, res) => {
  try {
    res.json({
      settings: getEffectiveSettings(),
      editableKeys: EDITABLE_SETTING_KEYS,
    });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

settingsRouter.put('/', (req, res) => {
  try {
    const payload = (req.body as { settings?: Record<string, unknown> })?.settings ?? {};
    const settings = saveSettings(payload);
    res.json({ ok: true, settings });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});
