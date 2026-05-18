const palettes = {
  tech: 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200',
  financial: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
  business: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
  industry: 'border-indigo-400/30 bg-indigo-400/10 text-indigo-200',
  default: 'border-slate-700 bg-slate-800 text-slate-300',
}

const groups = {
  tech: ['ai', 'ml', 'cloud', 'quantum', 'blockchain', 'web3', 'iot', 'cyber', 'robot', 'xr', 'vr', 'ar', 'biotech', 'space', 'semiconductor'],
  financial: ['fintech', 'defi', 'capital', 'investment', 'valuation', 'ma', 'venture', 'ipo', 'risk', 'market', 'finance'],
  business: ['gtm', 'pricing', 'product', 'strategy', 'ops', 'talent', 'partnership', 'competition', 'growth', 'organisation'],
  industry: ['health', 'retail', 'commerce', 'manufacturing', 'energy', 'media', 'logistics', 'estate', 'legal', 'gov', 'supply'],
}

function toneForTopic(topic) {
  const normalized = topic.toLowerCase()
  for (const [group, keywords] of Object.entries(groups)) {
    if (keywords.some((keyword) => normalized.includes(keyword))) {
      return palettes[group]
    }
  }
  return palettes.default
}

export default function TopicCloud({ topics, activeTopic, onSelect }) {
  if (!topics?.length) {
    return <p className="text-sm text-slate-500">Topics will appear here as ideas are saved.</p>
  }

  return (
    <div className="flex flex-wrap gap-2">
      {topics.map((topic) => {
        const active = topic === activeTopic
        return (
          <button
            key={topic}
            type="button"
            onClick={() => onSelect(active ? null : topic)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${toneForTopic(topic)} ${
              active ? 'ring-2 ring-white/30' : 'hover:brightness-110'
            }`}
          >
            {topic}
          </button>
        )
      })}
    </div>
  )
}
