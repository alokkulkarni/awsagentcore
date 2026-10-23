// Checks a designer API key and workspace work (lists the applications; changes nothing).
import { ListApplicationsCommand } from 'amazon-connect-acxd-sdk';
import { all, client, log } from './lib.mjs';

const apps = await all(client(), ListApplicationsCommand);
log('ok', `The key works for workspace ${process.env.ACXD_WORKSPACE_ID}: ${apps.length} application(s)`
  + `${apps.length ? ` (${apps.map((a) => a.name).join(', ')})` : ''}`);
