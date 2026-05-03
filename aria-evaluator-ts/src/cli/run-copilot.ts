#!/usr/bin/env node

export {};
process.env['EVAL_PROVIDER'] = 'copilot';
await import('./run.js');
