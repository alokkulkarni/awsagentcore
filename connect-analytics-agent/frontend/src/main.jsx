import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// Guard: if an MSAL auth popup ever lands on the SPA root (auth code in the
// URL + an opener window), don't boot the dashboard inside the popup — the
// opener only needs to read the URL and close this window.
const isAuthPopup =
  window.opener && window.opener !== window &&
  /[#?&](code|error)=/.test(`${window.location.hash}${window.location.search}`);

if (isAuthPopup) {
  document.getElementById('root').innerHTML =
    '<p style="font-family: system-ui, sans-serif; padding: 2rem; color: #475569;">Completing Microsoft 365 sign-in…</p>';
} else {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
