// src/conversation/scenario-loader.ts
// Loads YAML scenario files, handles multi-document files (--- separator),
// and performs template substitution of {customer_name} etc.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import yaml from 'js-yaml';
import type { Scenario, TemplateVars } from '../types/index.js';

/** Load all scenarios from a directory tree recursively */
export function loadScenariosFromDir(dir: string, rootDir?: string): Scenario[] {
  const root = rootDir ?? dir;   // always relative to the top-level scenarios dir
  const results: Scenario[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      results.push(...loadScenariosFromDir(full, root));
    } else if (entry.endsWith('.yaml') || entry.endsWith('.yml')) {
      results.push(...loadScenariosFromFile(full, root));
    }
  }
  return results;
}

/** Load one or more scenarios from a YAML file (multi-doc supported via ---) */
export function loadScenariosFromFile(filePath: string, baseDir?: string): Scenario[] {
  const content = readFileSync(filePath, 'utf-8');
  const docs = yaml.loadAll(content) as Array<Partial<Scenario>>;
  return docs
    .filter((d) => d && d.name)
    .map((doc, idx) => ({
      ...doc,
      filePath: baseDir
        ? `${relative(baseDir, filePath)}#${idx}`
        : `${filePath}#${idx}`,
    } as Scenario));
}

/** Filter scenarios by an optional filter string (matched against filePath prefix) */
export function filterScenarios(
  scenarios: Scenario[],
  filter?: string,
  channel?: 'chat' | 'voice',
): Scenario[] {
  let result = scenarios;
  if (filter) {
    const norm = filter.replace(/\\/g, '/').replace(/\.ya?ml$/i, '');
    result = result.filter((s) => s.filePath?.startsWith(norm));
  }
  if (channel) {
    // When running on voice, accept both voice-tagged and chat-tagged scenarios
    // (voice is a superset — any chat scenario can be run over voice).
    result = result.filter((s) => s.channel === channel || (channel === 'voice' && s.channel === 'chat'));
  }
  return result;
}

/** Substitute {customer_name} etc. in all string fields of a scenario */
export function applyTemplateVars(scenario: Scenario, vars: TemplateVars): Scenario {
  // Safe replace: passes undefined/null through unchanged (script-mode scenarios omit some fields)
  const replace = (str: string | undefined): string | undefined => {
    if (str == null) return str;
    return str.replace(/\{(\w+)\}/g, (_, key: string) => vars[key] ?? `{${key}}`);
  };

  return {
    ...scenario,
    name: replace(scenario.name) ?? scenario.name,
    description: scenario.description ? replace(scenario.description) : undefined,
    goal: replace(scenario.goal),
    customer_persona: replace(scenario.customer_persona),
    opening_message: replace(scenario.opening_message),
  } as Scenario;
}
