import ConnectChatWidget from './components/ConnectChatWidget';
import './App.css';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-mark">M</span>
            <span className="logo-text">Meridian Bank</span>
          </div>
          <nav className="nav">
            <a href="#accounts">Accounts</a>
            <a href="#payments">Payments</a>
            <a href="#support">Support</a>
          </nav>
        </div>
      </header>

      <main className="main">
        <section className="hero">
          <div className="hero-content">
            <h1>
              Banking made
              <span className="accent"> simple</span>
            </h1>
            <p className="hero-sub">
              Manage your accounts, make payments, and get instant help from
              ARIA — your AI banking assistant.
            </p>
            <div className="hero-cta">
              <button className="btn-primary">Open an Account</button>
              <button className="btn-secondary">Sign In</button>
            </div>
          </div>
          <div className="hero-visual" aria-hidden="true">
            <div className="card-preview">
              <div className="card-chip" />
              <div className="card-number">•••• •••• •••• 4821</div>
              <div className="card-footer">
                <span>Meridian Current</span>
                <span>James Hartley</span>
              </div>
            </div>
          </div>
        </section>

        <section className="features" id="accounts">
          <h2>Everything you need</h2>
          <div className="feature-grid">
            <div className="feature-card">
              <span className="feature-icon">💳</span>
              <h3>Instant Transfers</h3>
              <p>Send money anywhere in seconds with no hidden fees.</p>
            </div>
            <div className="feature-card">
              <span className="feature-icon">📊</span>
              <h3>Spending Insights</h3>
              <p>Understand your spending with intelligent categorisation.</p>
            </div>
            <div className="feature-card">
              <span className="feature-icon">🤖</span>
              <h3>ARIA Assistant</h3>
              <p>
                Get instant answers about your account, balances, and
                transactions — 24/7. Click the chat icon to start.
              </p>
            </div>
            <div className="feature-card">
              <span className="feature-icon">🔒</span>
              <h3>Bank-Grade Security</h3>
              <p>256-bit encryption and real-time fraud monitoring.</p>
            </div>
          </div>
        </section>
      </main>

      <footer className="app-footer">
        <p>© 2026 Meridian Bank plc. Authorised by the PRA and regulated by the FCA.</p>
      </footer>

      {/*
        ConnectChatWidget mounts invisibly and calls amazon_connect() once the
        widget script has finished loading. The chat button itself is rendered
        by the Connect widget library in a fixed-position overlay.
      */}
      <ConnectChatWidget />
    </div>
  );
}
