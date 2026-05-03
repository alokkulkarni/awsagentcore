#!/usr/bin/env node

export {};
process.env['EVAL_PROVIDER'] = 'connect';
await import('./run.js');
