#!/usr/bin/env node

export {};
process.env['EVAL_PROVIDER'] = 'azure';
await import('./run.js');
