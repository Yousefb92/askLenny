const PrismMark = () => (
  <svg viewBox="0 0 32 32" width={22} height={22} aria-hidden="true" style={{ flexShrink: 0 }}>
    <defs>
      <linearGradient id="tn-top" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%"   stopColor="#4a5fa8" />
        <stop offset="100%" stopColor="#1e2a50" />
      </linearGradient>
    </defs>
    <rect x="4" y="9" width="16" height="14" fill="#141c38" />
    <line x1="4"  y1="9" x2="4"  y2="23" stroke="#253058" strokeWidth="0.7" />
    <line x1="20" y1="9" x2="20" y2="23" stroke="#253058" strokeWidth="0.7" />
    <ellipse cx="12" cy="23" rx="8" ry="3" fill="#0e1525" stroke="#253058" strokeWidth="0.7" />
    <ellipse cx="12" cy="12" rx="8" ry="3" fill="none"    stroke="#1e2a48" strokeWidth="0.6" />
    <ellipse cx="12" cy="9"  rx="8" ry="3" fill="url(#tn-top)" stroke="#3d508a" strokeWidth="0.7" />
    <path d="M20,12 Q27,11 31,7"  stroke="#1fff90" strokeWidth="1.1" fill="none" />
    <path d="M20,16 Q28,16 31,16" stroke="#6677ff" strokeWidth="1.1" fill="none" />
    <path d="M20,20 Q27,21 31,25" stroke="#ff3fa0" strokeWidth="1.1" fill="none" />
  </svg>
)

const NAV_TABS = [
  { id: 'discovery',   label: 'Gap Discovery' },
  { id: 'graph',       label: 'Graph Visualiser' },
  { id: 'query',       label: 'Query Engine' },
]

export default function TopNav({ activeTab, onTabChange, pendingCount, onCommit, isCommitting }) {
  return (
    <nav className="top-nav">
      {/* Brand */}
      <div className="top-nav-brand">
        <PrismMark />
        <span className="top-nav-brand-word">
          <span className="top-nav-brand-ask">ask</span>
          <span className="top-nav-brand-lenny">Lenny</span>
        </span>
      </div>

      {/* Tabs */}
      <div className="top-nav-tabs">
        {NAV_TABS.map(tab => (
          <button
            key={tab.id}
            className={`top-nav-tab${activeTab === tab.id ? ' active' : ''}`}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Right actions */}
      <div className="top-nav-right">
        <button
          className="commit-btn"
          onClick={onCommit}
          disabled={isCommitting || pendingCount === 0}
        >
          {isCommitting ? 'Committing…' : 'Commit to Graph'}
          {pendingCount > 0 && (
            <span className="commit-badge">{pendingCount}</span>
          )}
        </button>
      </div>
    </nav>
  )
}
