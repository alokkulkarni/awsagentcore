#!/usr/bin/env node

export {};
process.env['EVAL_PROVIDER'] = 'strands';
await import('./run.js');
