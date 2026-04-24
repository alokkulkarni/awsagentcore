import ConnectChatWidget from './components/ConnectChatWidget';
import './App.css';

/* ── SVG product icons (Nationwide-style blue/red palette) ── */
const icons = {
  current: (
    <svg viewBox="0 0 80 72" xmlns="http://www.w3.org/2000/svg">
      <rect x="8" y="18" width="58" height="42" rx="4" fill="#4B78C8"/>
      <rect x="4" y="12" width="58" height="42" rx="4" fill="#6B94D8"/>
      <polygon points="62,12 62,0 80,12" fill="#E63012"/>
      <rect x="4" y="28" width="58" height="8" fill="#3A5FA0"/>
    </svg>
  ),
  mortgage: (
    <svg viewBox="0 0 80 72" xmlns="http://www.w3.org/2000/svg">
      <polygon points="40,4 72,30 8,30" fill="#E63012"/>
      <rect x="14" y="30" width="52" height="34" rx="2" fill="#4B78C8"/>
      <rect x="30" y="44" width="20" height="20" rx="2" fill="#3A5FA0"/>
    </svg>
  ),
  savings: (
    <svg viewBox="0 0 80 72" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="38" cy="42" rx="30" ry="24" fill="#4B78C8"/>
      <ellipse cx="38" cy="22" rx="16" ry="10" fill="#6B94D8"/>
      <rect x="60" y="36" width="10" height="12" rx="3" fill="#6B94D8"/>
      <circle cx="50" cy="46" r="4" fill="#3A5FA0"/>
      <rect x="34" y="64" width="8" height="6" rx="2" fill="#3A5FA0"/>
    </svg>
  ),
  insurance: (
    <svg viewBox="0 0 80 72" xmlns="http://www.w3.org/2000/svg">
      <path d="M10 34 Q10 8 40 8 Q70 8 70 34 Z" fill="#4B78C8"/>
      <path d="M36 34 L36 60 Q36 66 44 66 Q52 66 52 60 L52 34" stroke="#4B78C8" strokeWidth="6" fill="none"/>
      <line x1="40" y1="34" x2="40" y2="34" stroke="#4B78C8" strokeWidth="4"/>
    </svg>
  ),
  loans: (
    <svg viewBox="0 0 80 72" xmlns="http://www.w3.org/2000/svg">
      <circle cx="40" cy="36" r="28" fill="none" stroke="#4B78C8" strokeWidth="8"/>
      <circle cx="40" cy="36" r="10" fill="#4B78C8"/>
      <line x1="40" y1="8" x2="40" y2="20" stroke="#3A5FA0" strokeWidth="5"/>
      <line x1="68" y1="36" x2="56" y2="36" stroke="#3A5FA0" strokeWidth="5"/>
      <line x1="40" y1="64" x2="40" y2="52" stroke="#3A5FA0" strokeWidth="5"/>
      <line x1="12" y1="36" x2="24" y2="36" stroke="#3A5FA0" strokeWidth="5"/>
    </svg>
  ),
  creditcard: (
    <svg viewBox="0 0 80 56" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="2" width="76" height="52" rx="6" fill="#4B78C8"/>
      <rect x="2" y="16" width="76" height="12" fill="#3A5FA0"/>
      <rect x="10" y="36" width="20" height="10" rx="2" fill="#6B94D8"/>
    </svg>
  ),
  investments: (
    <svg viewBox="0 0 80 72" xmlns="http://www.w3.org/2000/svg">
      <rect x="4"  y="44" width="14" height="24" rx="2" fill="#4B78C8"/>
      <rect x="24" y="28" width="14" height="40" rx="2" fill="#4B78C8"/>
      <rect x="44" y="36" width="14" height="32" rx="2" fill="#E63012"/>
      <rect x="64" y="16" width="14" height="52" rx="2" fill="#4B78C8"/>
    </svg>
  ),
};

const products = [
  { key: 'current',    label: 'Current accounts',  href: '#current'  },
  { key: 'mortgage',   label: 'Mortgages',          href: '#mortgages'},
  { key: 'savings',    label: 'Savings and ISAs',   href: '#savings'  },
  { key: 'insurance',  label: 'Insurance',          href: '#insurance'},
  { key: 'loans',      label: 'Loans',              href: '#loans'    },
  { key: 'creditcard', label: 'Credit cards',       href: '#cards'    },
  { key: 'investments',label: 'Investments',        href: '#invest'   },
];

export default function App() {
  return (
    <div className="app">

      {/* ── Top header: logo + utility links ── */}
      <header className="app-header">
        <div className="header-top">
          <div className="header-inner">
            <div className="logo">
              <img src="/nationwide-logo.png" alt="Nationwide Building Society" className="logo-img" />
            </div>
            <div className="header-actions">
              <a href="#branch">Branch</a>
              <a href="#contact">Contact</a>
              <a href="#help">Help</a>
              <button className="btn-login">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                Log in
              </button>
            </div>
          </div>
        </div>

        {/* ── Product navigation ── */}
        <nav className="product-nav" aria-label="Product categories">
          <div className="product-nav-inner">
            {[
              'Current accounts','Savings and ISAs','Mortgages',
              'Loans','Credit cards','Insurance','Supporting you','Why Nationwide',
            ].map(item => (
              <a key={item} href={`#${item.toLowerCase().replace(/\s+/g,'-')}`}>
                {item} <span className="nav-caret">▾</span>
              </a>
            ))}
          </div>
        </nav>
      </header>

      <main className="main">

        {/* ── Hero ── */}
        <section className="hero">
          <div className="hero-inner">
            <div className="hero-content">
              <h1>A good way to <span className="accent">bank</span></h1>
              <div className="hero-lines">
                <p>We're a building society owned by our members, not shareholders. That difference changes everything.</p>
                <p>Which? Banking Brand of the Year 2025 – rated the UK's best high street banking provider for customer satisfaction.</p>
                <p>Bank how you choose – on our app, online or in branch.*</p>
              </div>
              <button className="btn-discover">Discover a good way to bank</button>
            </div>

            {/* Award badges */}
            <div className="hero-awards" aria-hidden="true">
              <div className="award-badge">
                <span className="award-year">2025</span>
                <span className="award-which">Which?</span>
                <span className="award-which-sub">Awards</span>
                <span className="award-desc">BANKING BRAND OF THE YEAR</span>
              </div>
              <div className="award-badge">
                <span className="award-year">NOVEMBER 2025</span>
                <span className="award-which">Which?</span>
                <span className="award-which-sub">Recommended<br/>Provider</span>
                <span className="award-desc">CURRENT ACCOUNTS</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── Products ── */}
        <section className="products-section">
          <div className="section-inner">
            <h2>What are you looking for today?</h2>
            <div className="products-grid">
              {products.map(({ key, label, href }) => (
                <div className="product-item" key={key}>
                  <div className="product-icon">{icons[key]}</div>
                  <a href={href}>{label}</a>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Promo cards ── */}
        <section className="promos-section">
          <div className="section-inner">
            <div className="promos-grid">
              <div className="promo-card promo-card--blue">
                <div className="promo-deco promo-deco--arrow" aria-hidden="true">
                  <svg viewBox="0 0 120 120" width="120" height="120">
                    <path d="M10 100 Q40 20 100 10" stroke="#E63012" strokeWidth="12" fill="none" strokeLinecap="round"/>
                    <polygon points="90,4 110,20 88,26" fill="#E63012"/>
                    <rect x="20" y="70" width="50" height="40" rx="4" fill="#6B94D8" opacity=".7"/>
                  </svg>
                </div>
                <div className="promo-text">
                  <h3>Switch to Nationwide</h3>
                  <p>More people move to us than any other current account provider.*</p>
                </div>
              </div>
              <div className="promo-card promo-card--blue">
                <div className="promo-deco promo-deco--dots" aria-hidden="true">
                  <svg viewBox="0 0 120 120" width="120" height="120">
                    {Array.from({length:8}).map((_,r) =>
                      Array.from({length:8}).map((_,c) => (
                        <circle key={`${r}-${c}`} cx={c*14+8} cy={r*14+8} r="4"
                          fill="#E63012" opacity={(r+c)%3===0 ? .9 : .3}/>
                      ))
                    )}
                  </svg>
                </div>
                <div className="promo-text">
                  <h3>Every branch staying open</h3>
                  <p>All our branches will remain open until at least the start of 2030.</p>
                </div>
              </div>
            </div>
          </div>
        </section>

      </main>

      <footer className="app-footer">
        <p>© 2026 Nationwide Building Society. Authorised by the PRA and regulated by the FCA and PSR. *PayUK data, 12 months to January 2026.</p>
      </footer>

      <ConnectChatWidget />
    </div>
  );
}

