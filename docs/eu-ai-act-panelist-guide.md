# EU AI Act Reality Check: From Principle to Practice
## Panelist Talking Points & iA Presenter Slides

> **Event format:** Panel discussion  
> **Session date context:** May 2026 — 3 months before the August 2026 high-risk AI compliance deadline  
> **Your role:** Panelist — expected to offer sharp, well-grounded perspective on compliance, high-risk AI classification, and practical implementation realities  

---

## Your Panelist Persona

You are a practitioner who has been in the room when these AI systems were being built and deployed — not just reading about the Act from a policy perspective, but living with its technical and organisational implications day-to-day. Your credibility comes from specificity. Avoid vague policy-speak; instead anchor every point in what actually happens at the implementation layer.

---

## PART 1 — When the Moderator Introduces You (30–60 seconds)

**What to say:**

> "Thanks — and I want to say upfront: I think the EU AI Act is genuinely important legislation. But we're standing in May 2026 — three months out from the August high-risk deadline — and if I'm honest with you, a lot of organisations I talk to are still treating compliance as a documentation exercise rather than an engineering discipline. That gap between principle and practice is exactly what I want to dig into today."

**Why this works:**  
It signals you're not here to cheerlead or fear-monger. It immediately anchors the discussion in the live, urgent reality (T-minus 90 days to the deadline). It sets up honest tension — exactly what a good panel needs.

---

## PART 2 — On Compliance: The Gap Between Paperwork and Practice

### Core Thesis to Own
> *"Compliance is not a PDF. It's an ongoing engineering and organisational commitment — and the Act's requirements implicitly demand a level of ML engineering maturity that most organisations simply haven't built yet."*

---

### Talking Point 1 — The Conformity Assessment Trap

**What to say:**

> "The Act mandates conformity assessments for high-risk systems. Sounds reasonable. But when you drill into what that actually requires — technical documentation covering the entire development lifecycle, logs of data governance decisions, evidence that your validation sets are representative — most teams discover they haven't been capturing this information as they build. So now they're retrospectively reconstructing the paper trail for systems that have been in production for two years. That's not compliance, that's archaeology."

**Supporting detail:**  
- Article 11 requires technical documentation to be maintained throughout the lifecycle of the system — not just at deployment.  
- Annex IV lists 12 categories of documentation including training data characteristics, accuracy metrics, and human oversight measures.  
- The challenge: most MLOps pipelines were not built with this audit trail in mind. Retrofitting it is expensive.

**Provocative angle:**  
> "We have a generation of data science teams who were hired to build great models, not great documentation. That's a culture problem, not just a tooling problem."

---

### Talking Point 2 — The Harmonised Standards Void

**What to say:**

> "Here's something that doesn't get enough airtime: the harmonised technical standards that are supposed to tell you *how* to demonstrate compliance — the ISO/IEC standards under the CEN/CENELEC mandate — are still being finalised. So organisations are being asked to comply with requirements like 'accuracy, robustness, and cybersecurity' without agreed metrics for what those words mean in a specific domain. You're compliant until a regulator decides you're not."

**Supporting detail:**  
- CEN/CENELEC JTC 21 is producing the harmonised standards, but several are still in draft or recently published — with no grace period for adoption.  
- This is not unlike GDPR in 2018, where guidance lagged the legislation by 12–18 months.  
- The practical result: organisations are taking a 'reasonable interpretation' stance, which creates legal risk.

**Provocative angle:**  
> "The Act set the destination but hasn't finished printing the map. Right now, legal teams are doing what they always do when there's ambiguity — they're being conservative to the point of paralysis."

---

### Talking Point 3 — SME Compliance Reality

**What to say:**

> "There's a serious equity issue here. The compliance architecture the Act envisions — notified bodies, quality management systems, post-market monitoring — was designed with large organisations in mind. The exemptions for SMEs help at the margins, but if you're a 30-person startup building a hiring-support tool that falls under Annex III, you're looking at a compliance cost that could be existential. That's not a bug in the Act, but it is a real-world consequence we should name."

**Supporting detail:**  
- Recital 90 and Article 9 include some SME considerations, but the core obligations don't change.  
- Estimates for full conformity assessment for a complex high-risk system range from €50k to €500k+ depending on the domain and whether a notified body is required.  
- Risk: innovation migrates to jurisdictions with lighter AI regulation, particularly for the startup ecosystem.

---

### Talking Point 4 — What Good Compliance Actually Looks Like

**What to say:**

> "I want to be constructive here, not just critical. The organisations I've seen handle this well have done three things. First, they treated the Act's requirements as a forcing function to improve their ML engineering practices — better data cards, better model cards, proper experiment tracking. Second, they embedded a 'compliance owner' inside the product team, not just in legal. Third, they built human oversight into the product UX, not as an afterthought. When those three things happen together, you end up with a better product *and* a compliant one. The law and good engineering are not in conflict — they're just asking the same thing in different languages."

---

## PART 3 — On High-Risk AI: The Classification Problem

### Core Thesis to Own
> *"The most consequential compliance decision any organisation will make is whether their system is high-risk. And that determination is harder, more ambiguous, and more consequential than most people realise."*

---

### Talking Point 1 — The Classification Decision Is Not Binary

**What to say:**

> "Everyone talks about 'high-risk AI' as though classification is obvious. It's not. Consider a virtual agent that handles customer complaints for a bank — does it fall under 'essential private and public services' under Annex III? Or an AI-powered scheduling tool in a hospital — is it a medical device or administrative software? The Act provides categories, but the boundaries between them require genuine legal and technical judgement. And the stakes of getting it wrong are asymmetric: under-classify and you're non-compliant; over-classify and you've just tripled your compliance burden."

**Supporting detail:**  
- Annex III lists 8 categories of high-risk use cases, each with sub-categories.  
- Article 6 introduces a two-step test: is it listed in Annex III AND does it pose a significant risk to health, safety, or fundamental rights?  
- The second limb — significant risk — requires a self-assessment, which creates subjectivity and legal uncertainty.

**Provocative angle:**  
> "There is a massive incentive to conclude your system is *not* high-risk. Every organisation is doing this assessment with their thumb on the scale — consciously or not."

---

### Talking Point 2 — The Human Oversight Paradox

**What to say:**

> "Article 14 requires 'appropriate human oversight measures'. This sounds obvious — of course humans should stay in control. But think about how this plays out in practice. If you have an AI system making 50,000 decisions per day, 'human oversight' can't mean a human reviews each one. So you end up with statistical sampling, exception-based review, or audit trails after the fact. The Act doesn't prescribe which of these is acceptable, and that leaves organisations — and more importantly, the people affected by those decisions — in a grey area. Meaningful oversight is actually a hard engineering and UX problem."

**Supporting detail:**  
- The distinction between 'human-in-the-loop', 'human-on-the-loop', and 'human-in-command' matters enormously here.  
- For high-volume systems (fraud detection, credit scoring, content moderation), fully manual review is operationally impossible.  
- Best practice emerging: tiered review — automatic approval within confidence thresholds, flagged review at edges, periodic retrospective auditing.

**Provocative angle:**  
> "We risk creating a fiction of human oversight — where a button exists, a human clicks it, but nobody can actually explain the decision they're approving. That is not what the Act intends, and it won't survive regulatory scrutiny."

---

### Talking Point 3 — Data Governance as the Real Compliance Bottleneck

**What to say:**

> "If you ask me what keeps compliance leads up at night, it's Article 10 — data governance. Training data must be relevant, sufficiently representative, and free from errors. For systems that were trained on large, heterogeneous datasets — including any system built on top of foundation models — the documentation trail for data provenance is often incomplete or entirely absent. You're building on borrowed data foundations and the Act is asking you to have a clean title deed."

**Supporting detail:**  
- Article 10 requires providers to examine data for possible biases and implement data governance practices covering the full pipeline.  
- For GPAI-based systems (GPT-class, Llama-class), the provider of the underlying model carries some obligations, but the deployer (the 'operator' in EU AI Act terminology) retains significant responsibilities.  
- The interplay between the AI Act and GDPR on training data is still being worked through by regulators — double compliance burden is real.

---

### Talking Point 4 — The GPAI Wildcard

**What to say:**

> "The General Purpose AI provisions — which kicked in August 2025 — introduced a whole new compliance layer that many people underestimated. If your organisation is building on top of a GPAI model — and almost every enterprise AI system today is — you need to understand the downstream responsibility chain. The GPAI provider handles systemic risk obligations; the deployer handles context-specific risk. But when something goes wrong, the regulator doesn't care about your contracts — they want someone accountable. Make sure your organisation knows exactly which obligations land with you versus your AI vendor."

**Supporting detail:**  
- GPAI models with systemic risk (>10^25 FLOPs training compute threshold as a proxy) face the heaviest obligations: adversarial testing, incident reporting, model evaluation.  
- As a deployer of GPAI, you inherit obligations around transparency, fundamental rights impact assessment for certain use cases, and post-deployment monitoring.  
- The contractual relationships between GPAI providers and deployers are still being negotiated — watch for model cards and transparency documentation from your AI vendors becoming contractually mandated.

---

## PART 4 — Final Comments (2–3 minutes)

### Core Thesis to Close On
> *"The EU AI Act is not the finish line — it's the starting gun for building AI systems that are genuinely trustworthy, not just technically compliant."*

---

### Final Comment 1 — The Bigger Picture

**What to say:**

> "I want to zoom out for a moment. The EU AI Act is historically significant — it's the first comprehensive legal framework for AI anywhere in the world. Whatever its imperfections, it has already changed the global conversation. It's influencing AI governance in the UK, Singapore, India, and increasingly in the US where federal AI legislation is finally gaining traction. We should not mistake critiquing the Act's implementation complexity for critiquing its purpose. The purpose is right."

---

### Final Comment 2 — The Competitive Framing Is a Distraction

**What to say:**

> "There's a narrative — often pushed by those who'd prefer less regulation — that the EU AI Act is a competitive disadvantage. That Europe will fall behind because it's over-regulating. I reject that framing. The organisations I see taking compliance seriously are also building better AI systems — more robust, more explainable, more trusted by their users. In a world where AI trust is becoming a buying decision, being genuinely compliant will be a differentiator, not a handicap. The question isn't 'how do we avoid this?' — it's 'how do we do this well?'"

---

### Final Comment 3 — The Call to Action (Practical)

**What to say:**

> "If you're in a product or engineering role and you leave this panel today thinking compliance is someone else's problem — I want to challenge that. The documentation requirements, the data governance practices, the human oversight mechanisms — these all require technical decisions that can only be made by the people building the systems. Compliance has to be designed in, not audited in. The teams that understand that are the ones that will navigate this well. So my ask is simple: in your next sprint planning session, put 'EU AI Act' on the agenda — not as a legal item, but as an engineering item."

---

### Final Comment 4 — The Honest Uncertainty

**What to say:**

> "I'll close with something I think we all need to be honest about: nobody has done this before. The regulators are learning, the organisations are learning, the courts are learning. There will be enforcement actions in the next 18 months that establish precedents we can't predict today. The right posture isn't to wait for clarity — it's to build systems you're genuinely proud to defend, document your decisions honestly, and stay engaged with the guidance as it evolves. The principle the Act is trying to enshrine — that AI should be safe, transparent, and accountable — that's worth the effort."

---

## PART 5 — Panel Q&A Preparation

### Q: "Isn't the August 2026 deadline already too late for most organisations?"

**Suggested response:**

> "It depends on what you mean by 'late'. If you mean 'is it too late to do it perfectly?' — yes, almost certainly. If you mean 'is it too late to do it meaningfully?' — no. The regulators have signalled they're more interested in demonstrable good-faith effort and a credible compliance roadmap than in perfection on day one. The organisations that are genuinely in trouble are the ones that haven't started, not the ones that have started imperfectly."

---

### Q: "How should organisations prioritise — which high-risk systems first?"

**Suggested response:**

> "Start with the systems where a failure has the highest human impact. Not the highest business impact — the highest impact on the people your system is making decisions about. Employment decisions, credit access, healthcare triage — these are the areas where the Act's protections matter most, and where regulators will focus first. Get those right. Then work outward from there."

---

### Q: "What's your take on GPAI — is the 10^25 FLOP threshold the right test?"

**Suggested response:**

> "The threshold is a blunt proxy for something much harder to measure — actual systemic risk. It will need to evolve as compute efficiency improves. A model trained at 10^24 FLOPs with a highly efficient architecture might pose more systemic risk than one at 10^26 with a naive architecture. The Commission has acknowledged this and reserved the right to update the threshold. For now, treat it as a starting point for the conversation, not the end of it."

---

### Q: "Should smaller companies just wait for the big players to set the compliance template?"

**Suggested response:**

> "That's tempting, but it's a trap. The big players have resources to over-engineer their compliance posture — their templates will be more complex than what a smaller organisation actually needs. My advice: follow the spirit of the Act's requirements for your scale, document your risk assessment honestly, and build a relationship with your industry association so you understand sector-specific guidance as it emerges. Don't copy-paste a FAANG compliance framework onto a 50-person company."

---

### Q: "Is the Act technology-neutral enough to survive the next wave of AI capabilities?"

**Suggested response:**

> "It's deliberately technology-neutral at the principles level, which is the right choice — you don't legislate for a specific technique like you don't legislate for a specific database engine. But the risk classification in Annex III is use-case based, and the use cases of 2026 are not the use cases of 2030. Agentic AI — systems that take actions in the world autonomously over extended periods — creates compliance scenarios the Act didn't fully anticipate. Human oversight of an agent that can browse the web, write code, and execute transactions looks very different from oversight of a classification model. Expect significant guidance updates in the next 2–3 years."

---

## iA Presenter Slide Deck

```markdown
# EU AI Act Reality Check
## From Principle to Practice

	[Your Name] · [Event Name] · May 2026

---

# About Me

	[Brief bio — 2–3 lines]
	[Role / organisation]
	[@handle or website]

---

# Where We Are Right Now

	📅 May 2026
	⏰ 3 months to the high-risk AI deadline
	⚡ Most organisations are still in sprint mode

Not a dress rehearsal. This is happening.

---

# The Central Tension

The Act asks for **compliance**.
The market asks for **speed**.
Engineering asks for **clarity**.

	All three want the same thing — they just don't know it yet.

---

# COMPLIANCE

---

# What Compliance Actually Requires

	✓ Technical documentation — full lifecycle
	✓ Conformity assessments (Annex IV)
	✓ Data governance records
	✓ Human oversight mechanisms
	✓ Post-market monitoring

Not a one-time audit. An ongoing discipline.

---

# The Archaeology Problem

Most teams haven't been capturing the information the Act requires.

	→ Retrospectively reconstructing paper trails
	→ For systems live for 2+ years
	→ That's not compliance — it's archaeology

// pause here for effect

---

# The Harmonised Standards Gap

Standards that define *how* to prove compliance...

	...are still being finalised.

"Accuracy, robustness, cybersecurity" — without agreed metrics.

	You're compliant until a regulator decides you're not.

---

# What Good Compliance Looks Like

Three things the best organisations do:

	1. Treat requirements as an ML engineering improvement
	2. Embed a compliance owner *inside* the product team
	3. Build human oversight into the UX — not as an afterthought

The Act and good engineering speak the same language.

---

# HIGH-RISK AI

---

# The Classification Problem

	Annex III: 8 categories, multiple sub-categories
	Article 6: two-step test — listed AND significant risk

The second limb requires a self-assessment.

	Translation: you assess your own risk.
	Everyone has a thumb on the scale.

---

# Examples That Aren't Obvious

	🏦 Bank virtual agent → essential private services?
	🏥 Hospital scheduling tool → medical device or admin software?
	💼 Hiring support tool → employment, Annex III category 4?

Getting it wrong in either direction is expensive.

---

# The Human Oversight Paradox

Article 14: "appropriate human oversight measures"

	50,000 decisions per day
	≠ 50,000 human reviews per day

So what does meaningful oversight actually look like?

	→ Tiered review by confidence threshold
	→ Exception-based escalation
	→ Retrospective auditing
	
The Act doesn't specify. That's a problem.

---

# The Fiction We Can't Afford

	Human clicks a button.
	Approves a decision they can't explain.
	
	That is not oversight.
	
That won't survive regulatory scrutiny — and it shouldn't.

---

# Data Governance — The Real Bottleneck

Article 10: training data must be relevant, representative, error-free.

	For systems built on foundation models:
	→ Data provenance is often incomplete
	→ You're building on borrowed foundations
	→ The Act asks for a clean title deed

// this is where most compliance programmes quietly stall

---

# GPAI — The Wildcard

	August 2025: GPAI provisions live
	>10²⁵ FLOPs → systemic risk obligations
	
	GPAI provider: adversarial testing, incident reporting
	You (the deployer): context-specific risk, transparency

Your contract with your AI vendor is now a compliance document.

---

# FINAL THOUGHTS

---

# This Is Bigger Than Europe

The EU AI Act is influencing:

	🇬🇧 UK AI governance framework
	🇸🇬 Singapore FEAT + MAS guidance
	🇮🇳 India AI policy development
	🇺🇸 US federal AI legislation momentum

Whatever you build to comply here works everywhere.

---

# The Competitive Narrative Is Wrong

"The Act puts Europe at a competitive disadvantage."

	Counter-evidence:
	→ Compliant systems are more robust
	→ Compliant systems are more trusted
	→ AI trust is becoming a buying decision

Being genuinely compliant will be a differentiator.

---

# My Ask — Before Your Next Sprint

Compliance is not a legal item.
It's an engineering item.

	"Is this system high-risk?"
	"How are we documenting data decisions?"
	"What does human oversight look like in our UX?"

Put these on your sprint agenda.

---

# The Honest Reality

Nobody has done this before.

	Regulators are learning.
	Organisations are learning.
	Courts are learning.

The right posture:

	→ Build systems you're proud to defend
	→ Document your decisions honestly
	→ Stay engaged as guidance evolves

---

# The Principle Is Worth the Effort

The Act is trying to ensure AI is:

	✓ Safe
	✓ Transparent
	✓ Accountable

Those aren't compliance checkboxes.
They're the right way to build AI.

---

# Thank You

	[Your Name]
	[Role / Organisation]
	[@handle]
	[website or QR code]

Slides & references: [URL]
```

---

## Quick Reference Card (for the panel table)

| Topic | One-line position | Evidence/hook |
|---|---|---|
| Compliance | It's an engineering discipline, not a documentation exercise | Article 11 + Annex IV requirements; retrospective paper trails |
| Harmonised standards | Compliance rules exist; implementation standards don't (yet) | CEN/CENELEC JTC 21 still drafting |
| SME burden | Compliance costs are asymmetric; existential for startups | €50k–€500k+ conformity assessment estimates |
| High-risk classification | The self-assessment creates inherent bias toward under-classification | Article 6 two-step test |
| Human oversight | "Meaningful oversight" at scale is an unsolved UX+engineering problem | Article 14; tiered review patterns |
| Data governance | Foundation model deployments lack clean data provenance chains | Article 10 |
| GPAI | Deployers underestimate inherited obligations | August 2025 GPAI provisions |
| Final message | Compliance and good engineering are the same thing | 3 practical steps for next sprint |

---

*Guide prepared: May 2026 | EU AI Act enforcement timeline: Prohibited AI (Feb 2025) ✓ · GPAI (Aug 2025) ✓ · High-Risk AI (Aug 2026) ← you are here*
