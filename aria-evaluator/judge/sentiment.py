"""
judge/sentiment.py
==================
Per-turn and aggregate sentiment analysis using the Bedrock Converse API.

Returns a SentimentReport with:
  - per_turn: list of {turn_index, role, content_preview, sentiment, confidence}
  - aggregate: overall session sentiment (positive/neutral/negative)
  - trend: improving | stable | deteriorating
  - score: 0.0–1.0 (1.0 = very positive throughout)
"""

import json
import logging
import re
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError

from channels.chat_adapter import ConversationLog

logger = logging.getLogger(__name__)


@dataclass
class TurnSentiment:
    turn_index: int
    role: str
    content_preview: str
    sentiment: str       # positive | neutral | negative
    confidence: float    # 0.0–1.0
    explanation: str = ""


@dataclass
class SentimentReport:
    per_turn: list[TurnSentiment] = field(default_factory=list)
    aggregate: str = "neutral"     # positive | neutral | negative
    trend: str = "stable"          # improving | stable | deteriorating
    score: float = 0.5             # 0.0–1.0
    summary: str = ""


class SentimentAnalyser:
    """
    Analyses customer sentiment in a ConversationLog using Bedrock Claude.

    Usage::

        analyser = SentimentAnalyser(model_id="eu.anthropic...", region="eu-west-2")
        report = analyser.analyse(conversation_log)
    """

    def __init__(self, model_id: str, region: str = "eu-west-2") -> None:
        self.model_id = model_id
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)

    def analyse(self, log: ConversationLog) -> dict:
        """Analyse sentiment and return a serialisable dict."""
        report = self._analyse_log(log)
        return {
            "aggregate": report.aggregate,
            "trend": report.trend,
            "score": report.score,
            "summary": report.summary,
            "per_turn": [
                {
                    "turn_index": t.turn_index,
                    "role": t.role,
                    "content_preview": t.content_preview,
                    "sentiment": t.sentiment,
                    "confidence": t.confidence,
                    "explanation": t.explanation,
                }
                for t in report.per_turn
            ],
        }

    # ── Private ─────────────────────────────────────────────────────────────

    def _analyse_log(self, log: ConversationLog) -> SentimentReport:
        report = SentimentReport()
        customer_turns = [t for t in log.turns if t.role == "customer" and t.content]

        if not customer_turns:
            return report

        # Analyse each customer turn
        for turn in customer_turns:
            sentiment, confidence, explanation = self._classify_turn(turn.content)
            report.per_turn.append(TurnSentiment(
                turn_index=turn.turn_index,
                role=turn.role,
                content_preview=turn.content[:100],
                sentiment=sentiment,
                confidence=confidence,
                explanation=explanation,
            ))

        # Session-level analysis
        full_conversation = "\n".join(
            f"[Turn {t.turn_index}] {'Customer' if t.role == 'customer' else 'ARIA'}: {t.content}"
            for t in log.turns if t.content
        )
        report.aggregate, report.trend, report.score, report.summary = (
            self._analyse_session(full_conversation)
        )

        return report

    def _classify_turn(self, text: str) -> tuple[str, float, str]:
        """Classify a single customer message as positive/neutral/negative."""
        system_prompt = (
            "You are a sentiment analysis expert for a UK retail bank. "
            "Classify the customer's message sentiment. "
            'Respond ONLY in JSON: {"sentiment": "positive"|"neutral"|"negative", '
            '"confidence": 0.0-1.0, "explanation": "brief reason"}'
        )
        user_prompt = f'Customer message: "{text}"'

        try:
            resp = self.bedrock.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": 150, "temperature": 0.0},
            )
            raw = resp["output"]["message"]["content"][0]["text"]
            data = json.loads(re.search(r"\{[^{}]+\}", raw, re.DOTALL).group())
            return (
                data.get("sentiment", "neutral"),
                float(data.get("confidence", 0.5)),
                data.get("explanation", ""),
            )
        except Exception as exc:
            logger.debug("Turn sentiment classification failed: %s", exc)
            return "neutral", 0.5, ""

    def _analyse_session(self, conversation: str) -> tuple[str, str, float, str]:
        """Analyse overall session sentiment and trend."""
        system_prompt = (
            "You are a customer experience evaluator for a UK retail bank. "
            "Analyse the overall customer sentiment trajectory across the full conversation. "
            "Respond ONLY in JSON: {"
            '"aggregate": "positive"|"neutral"|"negative", '
            '"trend": "improving"|"stable"|"deteriorating", '
            '"score": 0.0-1.0, '
            '"summary": "2-sentence summary of customer emotional journey"}'
        )
        try:
            resp = self.bedrock.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": conversation}]}],
                inferenceConfig={"maxTokens": 300, "temperature": 0.0},
            )
            raw = resp["output"]["message"]["content"][0]["text"]
            data = json.loads(re.search(r"\{[^{}]+\}", raw, re.DOTALL).group())
            return (
                data.get("aggregate", "neutral"),
                data.get("trend", "stable"),
                float(data.get("score", 0.5)),
                data.get("summary", ""),
            )
        except Exception as exc:
            logger.debug("Session sentiment analysis failed: %s", exc)
            return "neutral", "stable", 0.5, ""
