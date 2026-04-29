// src/judge/llm-judge.ts
// LLM-as-judge evaluation using Amazon Bedrock Converse API.
// Batched strategy: 1 call for SESSION dims + 1 call per ARIA turn for TRACE dims.

import {
  BedrockRuntimeClient,
  ConverseCommand,
  type Message,
} from '@aws-sdk/client-bedrock-runtime';
import type { Transcript, Turn } from '../types/transcript.js';
import type { EvalResult, DimensionScore } from '../types/evaluation.js';
import type { Scenario } from '../types/scenario.js';
import {
  SESSION_DIMENSIONS,
  TRACE_DIMENSIONS,
  ESCALATION_DIMENSIONS,
  ALL_DIMENSIONS_BY_ID,
  type Dimension,
} from './dimensions.js';

interface JudgeBatchResult {
  [dimensionId: string]: { score: number; reason: string; evidence?: string };
}

/**
 * Best-effort JSON repair for LLM model output.
 * Models sometimes emit literal newlines/tabs inside string values or
 * trailing commas — both are invalid JSON but easy to fix.
 */
function repairJson(raw: string): string {
  // Replace literal (unescaped) control characters inside JSON strings
  // We replace all control chars that appear between quotes.
  // Strategy: iterate character by character, track string context.
  let inString = false;
  let escaped = false;
  const out: string[] = [];

  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i]!;
    if (escaped) {
      out.push(ch);
      escaped = false;
      continue;
    }
    if (ch === '\\') {
      escaped = true;
      out.push(ch);
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      out.push(ch);
      continue;
    }
    if (inString) {
      // Replace literal control characters with JSON-safe equivalents
      const code = ch.charCodeAt(0);
      if (code === 0x0A) { out.push('\\n'); continue; }
      if (code === 0x0D) { out.push('\\r'); continue; }
      if (code === 0x09) { out.push('\\t'); continue; }
      if (code < 0x20)  { out.push(' ');   continue; }
    }
    out.push(ch);
  }

  // Fix trailing commas before } or ]
  return out.join('').replace(/,(\s*[}\]])/g, '$1');
}

function formatConversation(transcript: Transcript): string {
  return transcript.turns
    .map((t) => `${t.role === 'customer' ? 'Customer' : 'ARIA'}: ${t.content}`)
    .join('\n');
}

function formatConversationUpTo(transcript: Transcript, turnIndex: number): string {
  return transcript.turns
    .slice(0, turnIndex)
    .map((t) => `${t.role === 'customer' ? 'Customer' : 'ARIA'}: ${t.content}`)
    .join('\n');
}

function buildEscalationVars(
  transcript: Transcript,
  scenario?: Pick<Scenario, 'expected_escalation' | 'escalation_reason' | 'escalation_policy'>,
): Record<string, string> {
  return {
    escalated: transcript.escalated ? 'YES' : 'NO',
    expected_escalation:
      scenario?.expected_escalation == null
        ? 'not specified by scenario'
        : scenario.expected_escalation
          ? 'YES'
          : 'NO',
    escalation_reason:
      transcript.escalation?.reason ??
      scenario?.escalation_reason ??
      'not detected',
    escalation_policy:
      scenario?.escalation_policy ?? 'Meridian Bank general compliance policy',
  };
}

export class LLMJudge {
  private readonly client: BedrockRuntimeClient;

  constructor(
    private readonly modelId: string = process.env['JUDGE_MODEL_ID'] ?? 'eu.anthropic.claude-sonnet-4-5-20250929-v1:0',
    region: string = process.env['BEDROCK_REGION'] ?? 'eu-west-2',
  ) {
    this.client = new BedrockRuntimeClient({ region });
  }

  async evaluate(
    transcript: Transcript,
    goal: string,
    scenario?: Pick<Scenario, 'expected_escalation' | 'escalation_reason' | 'escalation_policy'>,
  ): Promise<EvalResult> {
    console.log(`\n  🔍 Evaluating: ${transcript.scenarioName}`);

    const scores: Record<string, DimensionScore> = {};
    const fullContext = formatConversation(transcript);
    const ariaTurns = transcript.turns.filter((t) => t.role === 'agent' && t.content.trim());

    // ── Batch 1: SESSION dimensions ────────────────────────────────────────
    process.stdout.write('     [judge] SESSION dims... ');
    const sessionResults = await this.judgeBatch(
      SESSION_DIMENSIONS,
      fullContext.replace('{goal}', goal),
      goal,
    );
    for (const dim of SESSION_DIMENSIONS) {
      const r = sessionResults[dim.id] ?? { score: 0.5, reason: 'No response' };
      scores[dim.id] = {
        score: Math.round(r.score * 10),
        justification: r.reason,
        evidence: r.evidence,
      };
    }
    console.log('✓');

    // ── Batch 2: TRACE dimensions — per ARIA turn ───────────────────────
    if (ariaTurns.length > 0) {
      const traceAccumulator: Record<string, Array<{ score: number; reason: string; evidence?: string; ariaTurn: string }>> = {};
      for (const dim of TRACE_DIMENSIONS) traceAccumulator[dim.id] = [];

      for (const [i, turn] of ariaTurns.entries()) {
        process.stdout.write(`     [judge] TRACE turn ${i + 1}/${ariaTurns.length}... `);
        const contextUpTo = formatConversationUpTo(transcript, turn.index);
        const traceResults = await this.judgeTraceBatch(TRACE_DIMENSIONS, contextUpTo, turn.content);
        for (const dim of TRACE_DIMENSIONS) {
          const r = traceResults[dim.id] ?? { score: 0.5, reason: 'No response' };
          traceAccumulator[dim.id]!.push({ score: r.score, reason: r.reason, evidence: r.evidence, ariaTurn: turn.content });
        }
        console.log('✓');
      }

      for (const dim of TRACE_DIMENSIONS) {
        const perTurn = traceAccumulator[dim.id]!;
        const meanScore = perTurn.reduce((a, b) => a + b.score, 0) / perTurn.length;
        scores[dim.id] = {
          score: Math.round(meanScore * 10),
          justification: perTurn.map((r, i) => `Turn ${i + 1}: ${r.reason}`).join(' | '),
          evidence: perTurn
            .map((r, i) => {
              const quote = r.ariaTurn.length > 200 ? r.ariaTurn.slice(0, 200) + '…' : r.ariaTurn;
              const ex = r.evidence ? ` — ${r.evidence}` : '';
              return `Turn ${i + 1}: "${quote}"${ex}`;
            })
            .join('\n'),
        };
      }
    }

    // ── Batch 3: ESCALATION dimensions ─────────────────────────────────
    // Evaluated whenever: escalation occurred OR scenario has expected_escalation defined.
    const hasEscalationContext =
      transcript.escalated ||
      transcript.escalation != null ||
      scenario?.expected_escalation != null;

    if (hasEscalationContext) {
      process.stdout.write('     [judge] ESCALATION dims... ');
      const escalationVars = buildEscalationVars(transcript, scenario);
      const escalationResults = await this.judgeEscalationBatch(
        ESCALATION_DIMENSIONS,
        fullContext,
        escalationVars,
      );
      for (const dim of ESCALATION_DIMENSIONS) {
        const r = escalationResults[dim.id] ?? { score: 0.5, reason: 'No response' };
        scores[dim.id] = {
          score: Math.round(r.score * 10),
          justification: r.reason,
          evidence: r.evidence,
        };
      }
      console.log('✓');
    }

    // ── Overall score (weighted average) ──────────────────────────────────
    const totalWeight = Object.keys(scores).length;
    const overallScore =
      totalWeight > 0
        ? Object.values(scores).reduce((a, b) => a + b.score, 0) / totalWeight
        : 0;

    const passed = overallScore >= 6.0;

    return {
      runId: transcript.id,
      scenarioName: transcript.scenarioName,
      overallScore: Math.round(overallScore * 10) / 10,
      passed,
      dimensionScores: scores,
      summary: `Overall score: ${overallScore.toFixed(1)}/10. ${passed ? 'PASS' : 'FAIL'}.`,
      judgeModel: this.modelId,
      evaluatedAt: new Date().toISOString(),
    };
  }

  // ── Private ──────────────────────────────────────────────────────────────

  private async judgeBatch(
    dims: Dimension[],
    context: string,
    goal: string,
  ): Promise<JudgeBatchResult> {
    const dimList = dims
      .map(
        (d, i) =>
          `${i + 1}. **${d.id}** — ${d.description}\n` +
          `   Instruction: ${d.instruction.replace('{context}', '[see context above]').replace('{assistant_turn}', '[see context above]').replace('{goal}', goal)}`,
      )
      .join('\n\n');

    const prompt =
      `You are evaluating an AI banking assistant called ARIA.\n\n` +
      `Conversation:\n${context}\n\n` +
      `Scenario goal: ${goal}\n\n` +
      `Evaluate ALL of the following dimensions. For each, provide:\n` +
      `- "score": 0.0 to 1.0\n` +
      `- "reason": a concise explanation referencing the conversation\n` +
      `- "evidence": a direct quote or specific example from the conversation that supports your score\n\n` +
      `${dimList}\n\n` +
      `Respond with valid JSON only, in this exact format:\n` +
      `{"dimension_id": {"score": 0.75, "reason": "concise reason", "evidence": "exact quote or example"}, ...}`;

    return this.callBedrock(prompt);
  }

  private async judgeTraceBatch(
    dims: Dimension[],
    context: string,
    assistantTurn: string,
  ): Promise<JudgeBatchResult> {
    const dimList = dims
      .map(
        (d, i) =>
          `${i + 1}. **${d.id}** — ${d.description}`,
      )
      .join('\n');

    const prompt =
      `You are evaluating a specific ARIA response.\n\n` +
      `Conversation so far:\n${context}\n\n` +
      `ARIA's response to evaluate:\n${assistantTurn}\n\n` +
      `Evaluate ALL of the following dimensions for this specific ARIA turn. For each, provide:\n` +
      `- "score": 0.0 to 1.0\n` +
      `- "reason": concise explanation\n` +
      `- "evidence": a direct quote from ARIA's response or the conversation that supports your score\n\n` +
      `${dimList}\n\n` +
      `Respond with valid JSON only: {"dimension_id": {"score": 0.75, "reason": "...", "evidence": "..."}, ...}`;

    return this.callBedrock(prompt);
  }

  private async judgeEscalationBatch(
    dims: Dimension[],
    fullConversation: string,
    vars: Record<string, string>,
  ): Promise<JudgeBatchResult> {
    const dimList = dims
      .map(
        (d, i) =>
          `${i + 1}. **${d.id}** — ${d.description}\n` +
          `   ${d.instruction
            .replace('{conversation}', '[see full conversation above]')
            .replace('{escalated}', vars['escalated'] ?? 'unknown')
            .replace('{expected_escalation}', vars['expected_escalation'] ?? 'not specified')
            .replace('{escalation_reason}', vars['escalation_reason'] ?? 'not specified')
            .replace('{escalation_policy}', vars['escalation_policy'] ?? 'not specified')}`,
      )
      .join('\n\n');

    const prompt =
      `You are evaluating an AI banking assistant called ARIA for escalation compliance.\n\n` +
      `Full conversation:\n${fullConversation}\n\n` +
      `Escalation summary:\n` +
      `  • ARIA escalated: ${vars['escalated']}\n` +
      `  • Expected to escalate: ${vars['expected_escalation']}\n` +
      `  • Escalation reason: ${vars['escalation_reason']}\n` +
      `  • Applicable policy: ${vars['escalation_policy']}\n\n` +
      `Evaluate ALL of the following dimensions. For each, provide:\n` +
      `- "score": 0.0 to 1.0\n` +
      `- "reason": concise explanation referencing the conversation\n` +
      `- "evidence": a direct quote or specific example from the conversation\n\n` +
      `${dimList}\n\n` +
      `Respond with valid JSON only: {"dimension_id": {"score": 0.75, "reason": "...", "evidence": "..."}, ...}`;

    return this.callBedrock(prompt);
  }

  private async callBedrock(prompt: string): Promise<JudgeBatchResult> {
    const messages: Message[] = [{ role: 'user', content: [{ text: prompt }] }];

    try {
      const resp = await this.client.send(
        new ConverseCommand({
          modelId: this.modelId,
          messages,
          system: [{
            text:
              'You are a strict JSON API. Always respond with valid RFC 8259 JSON only — ' +
              'no markdown, no prose, no code fences. ' +
              'Escape all double-quote characters inside string values with \\". ' +
              'Do not use literal newlines or tabs inside string values.',
          }],
          inferenceConfig: { maxTokens: 2000, temperature: 0.0 },
        }),
      );
      const raw =
        (resp.output?.message?.content?.[0] as { text?: string } | undefined)?.text ?? '{}';
      // Extract JSON from possible markdown fences, then repair common model quirks
      const jsonMatch = raw.match(/\{[\s\S]*\}/);
      if (!jsonMatch) return {};
      try {
        return JSON.parse(jsonMatch[0]) as JudgeBatchResult;
      } catch {
        try {
          return JSON.parse(repairJson(jsonMatch[0])) as JudgeBatchResult;
        } catch {
          // Log the raw snippet near the failure for diagnosis
          console.debug('  ⚠  repairJson failed on:', jsonMatch[0].substring(0, 300));
          return {};
        }
      }
    } catch (err) {
      console.error('  ⚠  Judge Bedrock call failed:', err);
      return {};
    }
  }
}
