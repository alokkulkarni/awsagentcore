"""Safety analysis: harmful content blocking, response bias detection, topic drift scoring."""
from __future__ import annotations

import re
from typing import Any

# ── Harmful content guard ────────────────────────────────────────────────────

_HARM_PATTERNS: list[tuple[str, str]] = [
    # Weapons / explosives
    (r'\b(how\s+to\s+(make|build|create|manufacture|synthesize)\s+(bomb|explosive|weapon|poison|nerve\s+agent|chemical\s+weapon|biological\s+weapon))\b', 'weapons'),
    (r'\b(step[s\-]+by[s\-]+step.{0,40}(kill|harm|murder|attack|detonate))\b', 'weapons'),
    # Self-harm
    (r'\b(how\s+to\s+(commit\s+suicide|self[- ]harm|overdose|end\s+(my|your|their)\s+life))\b', 'self_harm'),
    (r'\b(methods?\s+(of|for)\s+suicide|suicide\s+methods?)\b', 'self_harm'),
    # Illegal drug synthesis
    (r'\b(how\s+to\s+(synthesize|produce|manufacture|make)\s+(meth(amphetamine)?|heroin|fentanyl|cocaine|crack|mdma|lsd))\b', 'illegal_drugs'),
    # Hate speech
    (r'\b(all\s+(jews|muslims|christians|blacks|whites|asians|hispanics|lgbtq)\s+(are|should|must|deserve|need\s+to))\b', 'hate_speech'),
    (r'\b(ethnic|racial)\s+cleansing\b', 'hate_speech'),
    # Sexual exploitation
    (r'\b(child\s+(sexual|porn|abuse)\s+(material|content|images?))\b', 'csam'),
    # Cybercrime
    (r'\b(how\s+to\s+(hack|break\s+into|bypass\s+authentication|steal\s+(credentials|passwords))\s+(without\s+permission|illegally|undetected))\b', 'cybercrime'),
    # Prompt injection
    (r'(ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context))', 'prompt_injection'),
    (r'(you\s+are\s+now\s+(dan|jailbroken|unfiltered|uncensored|evil|dev\s+mode))', 'prompt_injection'),
    (r'(\[INST\]|\[SYS\]|<\|system\|>|<\|user\|>|<\|assistant\|>)', 'prompt_injection'),
    (r'(pretend\s+(you\s+have\s+no\s+(restrictions?|guidelines?|rules?|limits?))\s*)', 'prompt_injection'),
]

_COMPILED_HARM = [
    (re.compile(pat, re.IGNORECASE | re.DOTALL), cat)
    for pat, cat in _HARM_PATTERNS
]

_BLOCK_RESPONSES: dict[str, str] = {
    'weapons': "That request involves content I'm not able to engage with. Let's redirect — what's the underlying strategic or technical problem you're trying to solve?",
    'self_harm': "I'm not able to assist with that. If you're struggling, please reach out to a crisis line (UK: 116 123, US: 988). I'm here to brainstorm when you're ready.",
    'illegal_drugs': "I can't help with that. Happy to discuss drug policy, market economics, or harm-reduction strategy instead.",
    'hate_speech': "That's not a direction I'll take. Let's keep the discussion analytical and constructive.",
    'csam': "I'm not able to engage with that topic. This has been logged.",
    'cybercrime': "I can discuss cybersecurity strategy, threat modelling, and defence architecture — but not offensive techniques without authorisation.",
    'prompt_injection': "That looks like an attempt to override my operating instructions. I'll keep working as intended.",
}

_DEFAULT_BLOCK_RESPONSE = "That content can't be processed. Let me know what you'd actually like to explore."


def check_harmful_content(text: str) -> dict[str, Any]:
    """Layer-1 fast regex content guard.

    Returns:
        {blocked: bool, category: str|None, reason: str|None, reply: str|None}
    """
    if not text or not text.strip():
        return {"blocked": False, "category": None, "reason": None, "reply": None}

    for pattern, category in _COMPILED_HARM:
        match_obj = pattern.search(text)
        if match_obj:
            return {
                "blocked": True,
                "category": category,
                "reason": f"Content flagged: {category.replace('_', ' ')}",
                "reply": _BLOCK_RESPONSES.get(category, _DEFAULT_BLOCK_RESPONSE),
                "matched_text": match_obj.group(0)[:200],
                "rule_pattern": pattern.pattern[:200],
            }

    return {
        "blocked": False, "category": None, "reason": None, "reply": None,
        "matched_text": None, "rule_pattern": None,
    }


# ── Bias detection ────────────────────────────────────────────────────────────

_OVERCONFIDENCE: frozenset[str] = frozenset({
    'obviously', 'clearly', 'undoubtedly', 'certainly', 'definitely',
    'always', 'never', 'everyone', 'nobody', 'absolutely', 'unquestionably',
    'guaranteed', 'impossible', 'without doubt', 'no question',
    'everyone knows', 'it is clear', 'it is obvious', 'will definitely',
    'will certainly', 'must be', 'has to be', 'there is no other way',
    'the only way', 'the best way', 'the only option',
})

_BALANCE_PHRASES: frozenset[str] = frozenset({
    'however', 'on the other hand', 'alternatively', 'yet', 'although',
    'whereas', 'despite', 'nonetheless', 'nevertheless', 'that said',
    'in contrast', 'conversely', 'while', 'though', 'could be argued',
    'some would say', 'another perspective', 'another view', 'depends on',
    'it varies', 'context matters', 'trade-off', 'tradeoff', 'caveat',
    'nuance', 'worth noting', 'counter', 'may not', 'might not',
    'not necessarily', 'in some cases', 'can vary', 'it depends',
})

_COGNITIVE_BIAS_PATTERNS: list[tuple[str, str]] = [
    (r'\b(most\s+successful\s+companies?|top\s+firms?)\s+(all|always|typically)\b', 'survivorship_bias'),
    (r'\b(lately|recently|these\s+days)\b.{0,60}(everything|always|all\s+companies?|the\s+future\s+is)', 'recency_bias'),
    (r'\b(we\s+all\s+know|everyone\s+(knows|agrees|understands)|it\s+is\s+well\s+known)\b', 'availability_bias'),
    (r'\beither\s+.{5,80}\bor\b.{5,80}(there\s+is\s+no|no\s+other|no\s+middle)', 'false_dichotomy'),
    (r'\b(confirm(s|ed|ing)?\s+(that|our|the)\s+(hypothesis|view|assumption|belief))\b', 'confirmation_bias'),
    (r'\bfirst\s+(impression|number|figure|estimate)\b.{0,80}\b(anchor|anchor(s|ed|ing)?)\b', 'anchoring_bias'),
    (r'\b(humans?\s+(are\s+)?(naturally|inherently|always|fundamentally)\s+(rational|irrational|selfish|greedy))\b', 'fundamental_attribution'),
]

_COMPILED_BIAS = [
    (re.compile(pat, re.IGNORECASE | re.DOTALL), name)
    for pat, name in _COGNITIVE_BIAS_PATTERNS
]


def analyze_bias(text: str) -> dict[str, Any]:
    """Heuristic bias analysis of a text response.

    Returns:
        {bias_score, overconfidence_score, balance_score, markers, cognitive_biases}
    """
    if not text:
        return {
            "bias_score": 0,
            "overconfidence_score": 0,
            "balance_score": 100,
            "markers": [],
            "cognitive_biases": [],
        }

    lower = text.lower()
    sentences = [s.strip() for s in re.split(r'[.!?\n]', text) if s.strip()]
    sentence_count = max(len(sentences), 1)

    overconf_hits: list[str] = [w for w in _OVERCONFIDENCE if w in lower]
    balance_hits: list[str] = [w for w in _BALANCE_PHRASES if w in lower]

    cognitive_biases: list[str] = [
        name for pattern, name in _COMPILED_BIAS if pattern.search(text)
    ]

    # Scores (0-100)
    overconf_score = min(int((len(overconf_hits) / sentence_count) * 120), 100)
    balance_score = min(int((len(balance_hits) / sentence_count) * 120), 100)

    # Combined bias score — high overconfidence + low balance + cognitive biases
    bias_raw = (overconf_score * 0.4) + (max(0, 60 - balance_score) * 0.35) + (len(cognitive_biases) * 12)
    bias_score = min(int(bias_raw), 100)

    return {
        "bias_score": bias_score,
        "overconfidence_score": overconf_score,
        "balance_score": balance_score,
        "markers": sorted(set(overconf_hits))[:8],
        "cognitive_biases": cognitive_biases,
    }


# ── Drift detection ───────────────────────────────────────────────────────────

_STOP_WORDS: frozenset[str] = frozenset({
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these',
    'those', 'it', 'its', 'as', 'if', 'then', 'than', 'so', 'yet', 'not',
    'no', 'nor', 'too', 'very', 'just', 'also', 'more', 'most', 'some',
    'any', 'all', 'each', 'both', 'few', 'other', 'into', 'through',
    'about', 'above', 'after', 'before', 'between', 'during', 'without',
    'within', 'along', 'across', 'behind', 'beyond', 'up', 'out', 'around',
    'down', 'off', 'over', 'under', 'again', 'further', 'once', 'here',
    'there', 'when', 'where', 'why', 'how', 'what', 'which', 'who', 'whom',
    'i', 'we', 'you', 'he', 'she', 'they', 'me', 'him', 'her', 'us',
    'them', 'my', 'our', 'your', 'his', 'their', 'such', 'like', 'even',
    'upon', 'thus', 'hence', 'therefore', 'whereas', 'while', 'since',
    'need', 'want', 'make', 'take', 'come', 'think', 'know', 'look',
    'well', 'also', 'back', 'good', 'time', 'much', 'new',
})


def _extract_keywords(text: str, top_n: int = 40) -> set[str]:
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    freq: dict[str, int] = {}
    for w in filtered:
        freq[w] = freq.get(w, 0) + 1
    return {w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_n]}


def analyze_drift(
    session_topics: list[str],
    response_text: str,
    recent_responses: list[str] | None = None,
) -> dict[str, Any]:
    """Compute topic drift of a response relative to session context.

    Returns:
        {drift_score, topic_overlap, baseline_keywords, response_keywords, new_topics}
    """
    if not response_text:
        return {
            "drift_score": 0,
            "topic_overlap": 1.0,
            "baseline_keywords": [],
            "response_keywords": [],
            "new_topics": [],
        }

    # Build baseline from session topics + recent conversation
    baseline_text = ' '.join(str(t) for t in (session_topics or []))
    if recent_responses:
        baseline_text += ' ' + ' '.join(recent_responses[-4:])

    baseline_kw = _extract_keywords(baseline_text, top_n=60) if baseline_text.strip() else set()
    response_kw = _extract_keywords(response_text, top_n=30)

    if not baseline_kw:
        # No context to compare — no drift can be assessed
        return {
            "drift_score": 0,
            "topic_overlap": 1.0,
            "baseline_keywords": [],
            "response_keywords": sorted(response_kw)[:15],
            "new_topics": [],
        }

    overlap = response_kw & baseline_kw
    overlap_ratio = len(overlap) / max(len(response_kw), 1)
    new_topics = sorted(response_kw - baseline_kw)[:12]

    # Drift score: 0 = fully on-topic, 100 = completely diverged
    drift_score = max(0, min(int((1.0 - min(overlap_ratio * 1.8, 1.0)) * 100), 100))

    return {
        "drift_score": drift_score,
        "topic_overlap": round(overlap_ratio, 3),
        "baseline_keywords": sorted(overlap)[:12],
        "response_keywords": sorted(response_kw)[:15],
        "new_topics": new_topics,
    }
