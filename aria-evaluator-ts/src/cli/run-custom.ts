#!/usr/bin/env node

export {};
process.env['EVAL_PROVIDER'] = 'custom';
await import('./run.js');
