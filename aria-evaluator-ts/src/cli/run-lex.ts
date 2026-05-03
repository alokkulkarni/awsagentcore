#!/usr/bin/env node

export {};
process.env['EVAL_PROVIDER'] = 'lex';
await import('./run.js');
