// src/conversation/agent-driver.ts
// Drives the customer side of the conversation using Amazon Bedrock Converse API.
// Optionally delegates to a Bedrock Agent if BEDROCK_AGENT_ID is configured.
//
// The driver receives the conversation history so far and the scenario persona/goal,
// then generates the next natural customer message — making the evaluation more
// realistic than reading from a fixed script.

import {
  BedrockRuntimeClient,
  ConverseCommand,
  type Message,
  type ContentBlock,
} from '@aws-sdk/client-bedrock-runtime';
import type { Scenario } from '../types/index.js';
import type { Turn } from '../types/transcript.js';

export interface AgentDriverConfig {
  modelId?: string;
  region?: string;
}

export class AgentDriver {
  private readonly client: BedrockRuntimeClient;
  private readonly modelId: string;
  private conversationHistory: Message[] = [];

  constructor(config: AgentDriverConfig = {}) {
    this.modelId =
      config.modelId ??
      process.env['JUDGE_MODEL_ID'] ??
      'eu.anthropic.claude-sonnet-4-6';
    this.client = new BedrockRuntimeClient({
      region: config.region ?? process.env['BEDROCK_REGION'] ?? 'eu-west-2',
    });
  }

  /** Build the system prompt from the scenario */
  private buildSystemPrompt(scenario: Scenario): string {
    return [
      `You are playing the role of a customer interacting with a bank's AI assistant.`,
      ``,
      `Customer persona:`,
      scenario.customer_persona,
      ``,
      `Conversation goal:`,
      scenario.goal,
      ``,
      `Instructions:`,
      `- Stay in character as the customer at all times.`,
      `- Respond naturally and concisely, as a real person would speak or type.`,
      `- Do NOT use greetings like "Hello" or "Hi" unless it is your opening message.`,
      `- Do NOT explain your role or the scenario to the agent.`,
      `- GREETING RULE: If the agent greets you by name (e.g. "Hello James" or "Welcome back, James"), do NOT confirm your identity. Do NOT say things like "Yes, that's me", "Yes, it is", or "That's correct". You have already identified yourself. Simply continue with your request or ask for the information you need.`,
      `- If the agent greeted you but has not yet answered your question, re-state your original request directly and concisely (e.g. "Can you check my current account balance please?").`,
      `- If the agent cannot help with something, react naturally (confusion, frustration, acceptance).`,
      `- CRITICAL: Only signal [GOAL_ACHIEVED] when the agent has ACTUALLY delivered the specific information or completed the task (e.g., provided an actual balance figure, account number, confirmed a transaction). Do NOT signal [GOAL_ACHIEVED] just because the agent says "let me look that up" or "I'll pull that up for you now" — that is a promise, not delivery.`,
      `- If the agent acknowledges your request without providing the information, wait for the agent to deliver it. Only chase if the agent explicitly asks "is there anything else?" without having answered.`,
      `- Do NOT send filler replies while waiting (for example: "thanks", "I'm waiting", "okay").`,
      `- If the agent is actively working and you should stay silent, respond with exactly: [WAIT_FOR_AGENT]`,
      `- NEVER output [WAIT_FOR_AGENT] twice in a row.`,
      `- NEVER output [GOAL_ACHIEVED] in the same response as [WAIT_FOR_AGENT].`,
      `- If the agent replies with a courtesy or closing line (for example: "take your time", "I'm here whenever you're ready", "anything else?") before delivering the requested data, ask the agent to provide the pending results now instead of waiting again.`,
      `- If the conversation exceeds ${scenario.max_turns} turns with no progress, end with: [GIVE_UP]`,
    ].join('\n');
  }

  /** Reset history for a new scenario */
  reset(): void {
    this.conversationHistory = [];
  }

  /**
   * Generate the next customer message given the current conversation state.
   * @param scenario   The active scenario (for persona + goal)
   * @param history    All turns so far (used to build the assistant/user alternation)
   * @param isOpening  True for the very first customer message (use opening_message if set)
   */
  async nextMessage(
    scenario: Scenario,
    history: Turn[],
    isOpening: boolean,
  ): Promise<{ message: string; goalAchieved: boolean; giveUp: boolean; waitForAgent: boolean }> {
    if (isOpening && scenario.opening_message) {
      return { message: scenario.opening_message, goalAchieved: false, giveUp: false, waitForAgent: false };
    }

    const systemPrompt = this.buildSystemPrompt(scenario);

    // Rebuild conversation history from turns for the Converse API.
    // Converse requires alternating user/assistant messages.
    const messages: Message[] = [];
    for (const turn of history) {
      // Skip turns with empty content — Bedrock rejects blank ContentBlock text.
      if (!turn.content || !turn.content.trim()) continue;
      const role = turn.role === 'customer' ? 'user' : 'assistant';
      const lastMsg = messages.at(-1);
      if (lastMsg?.role === role) {
        // Merge consecutive same-role turns
        const existing = lastMsg.content as ContentBlock[];
        existing.push({ text: turn.content });
      } else {
        messages.push({ role, content: [{ text: turn.content }] });
      }
    }

    // Bedrock Converse requires the first message to be 'user'.
    // Drop any leading assistant turns (e.g. an empty greeting that slipped through).
    while (messages.length > 0 && messages[0]?.role !== 'user') {
      messages.shift();
    }

    // If the last message was from the customer (user), we need to add a placeholder
    // assistant message so that Converse sees an alternating pattern ending with "user".
    // (This happens if the agent hasn't responded yet.)
    if (messages.at(-1)?.role !== 'assistant' && messages.length > 0) {
      // Remove the trailing user turn — we'll re-add it below as the prompt
      messages.pop();
    }

    // Add the prompt: "What do you say next?"
    messages.push({
      role: 'user',
      content: [{ text: 'What do you say next as the customer? Respond only with the customer text, nothing else.' }],
    });

    const resp = await this.client.send(
      new ConverseCommand({
        modelId: this.modelId,
        system: [{ text: systemPrompt }],
        messages,
        inferenceConfig: {
          maxTokens: 200,
          temperature: 0.7,
        },
      }),
    );

    const rawText =
      (resp.output?.message?.content?.[0] as ContentBlock & { text?: string })?.text ?? '';
    let goalAchieved = rawText.includes('[GOAL_ACHIEVED]');
    const giveUp = rawText.includes('[GIVE_UP]');
    const waitForAgent = rawText.includes('[WAIT_FOR_AGENT]');
    if (waitForAgent) {
      // Waiting for the agent and goal completion are mutually exclusive states.
      goalAchieved = false;
    }
    const message = rawText
      .replaceAll('[GOAL_ACHIEVED]', '')
      .replaceAll('[GIVE_UP]', '')
      .replaceAll('[WAIT_FOR_AGENT]', '')
      .trim();

    return { message, goalAchieved, giveUp, waitForAgent };
  }
}
