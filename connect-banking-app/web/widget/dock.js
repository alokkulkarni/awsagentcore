// Where the assistant sits on the page: a tag fixed at the bottom that opens an overlay.
//   phone (under 640px wide)   a bottom sheet; drag its handle to make it taller or shorter
//   tablet and desktop         a floating panel at the bottom right; drag its top-left corner to resize
// The overlay is not modal: the page keeps scrolling behind it. On a phone the page gets bottom padding
// equal to the sheet's height, so everything can still be scrolled into view above the sheet.
// It knows which page the customer is on (context(): { label, launcher }), and shows that as the conversation's
// context; once a conversation starts, it shows the page it started from.
// Sizes are remembered in this browser only (a convenience; everything works without it).

const PHONE = window.matchMedia('(max-width: 639px)');
const STORE_KEY = 'bankingAssistantSize';
const STEP = 40;

function remembered() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
}

export function setupDock({ context: pageContext }) {
  const $ = (id) => document.getElementById(id);
  const panel = $('talk-panel');
  const launcher = $('talk-launcher');
  const grip = $('talk-grip');
  const root = document.documentElement;
  const sizes = { phone: {}, wide: {}, ...remembered() };
  let startedOn = null;      // the page a live conversation started from
  let liveKind = '';         // 'chat' | 'call' | ''

  const mode = () => (PHONE.matches ? 'phone' : 'wide');
  const limits = () => (PHONE.matches
    ? { minH: 220, maxH: Math.round(window.innerHeight * 0.92), defH: Math.round(window.innerHeight * 0.55) }
    : { minH: 360, maxH: window.innerHeight - 48, defH: Math.min(600, window.innerHeight - 48),
        minW: 320, maxW: Math.min(720, window.innerWidth - 48), defW: window.innerWidth < 1024 ? 420 : 380 });
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, Math.round(n)));

  function size() {
    const l = limits();
    const s = sizes[mode()];
    return { h: clamp(s.h || l.defH, l.minH, l.maxH), w: PHONE.matches ? 0 : clamp(s.w || l.defW, l.minW, l.maxW), l };
  }

  function apply() {
    const { h, w, l } = size();
    panel.style.setProperty('--talk-h', `${h}px`);
    if (w) panel.style.setProperty('--talk-w', `${w}px`); else panel.style.removeProperty('--talk-w');
    // On a phone the sheet covers the bottom of the page: pad the page so it all still scrolls into view.
    const sheet = !panel.hidden && PHONE.matches;
    root.classList.toggle('talk-sheet-open', sheet);
    root.style.setProperty('--talk-pad', sheet ? `${h}px` : '');
    grip.setAttribute('aria-valuemin', String(l.minH));
    grip.setAttribute('aria-valuemax', String(l.maxH));
    grip.setAttribute('aria-valuenow', String(h));
    grip.setAttribute('aria-valuetext', `${h} pixels tall${w ? `, ${w} wide` : ''}`);
  }

  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(sizes)); } catch { /* private window: not remembered */ }
  }

  function resize(h, w) {
    const s = sizes[mode()];
    s.h = h;
    if (w !== undefined && !PHONE.matches) s.w = w;
    apply();
  }

  function context() {
    const now = pageContext();
    const about = (liveKind && startedOn) ? startedOn.label : now.label;
    $('talk-context').textContent = liveKind ? `Started from ${about}` : `About ${about}`;
    $('start-context').textContent = about;
    $('start-note').textContent = now.note || '';
    $('launcher-title').textContent = liveKind === 'call' ? 'Call in progress'
      : liveKind === 'chat' ? 'Chat in progress' : (now.launcher || 'Ask us anything');
    $('launcher-context').textContent = liveKind ? 'Tap to return' : about;
    launcher.classList.toggle('live', Boolean(liveKind));
  }

  function open() {
    panel.hidden = false;
    launcher.hidden = true;
    launcher.setAttribute('aria-expanded', 'true');
    context();
    apply();
    const first = liveKind === 'chat' ? $('chat-input') : liveKind ? $('talk-end') : $('talk-chat');
    first.focus({ preventScroll: true });
  }

  function minimise() {
    panel.hidden = true;
    launcher.hidden = false;
    launcher.setAttribute('aria-expanded', 'false');
    context();
    apply();
    launcher.focus({ preventScroll: true });
  }

  // Dragging the handle (phone: up and down) or the corner (wide: up, down, left and right).
  grip.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    grip.setPointerCapture(event.pointerId);
    const from = { x: event.clientX, y: event.clientY, ...size() };
    panel.classList.add('resizing');
    const move = (e) => resize(clamp(from.h + (from.y - e.clientY), from.l.minH, from.l.maxH),
      PHONE.matches ? undefined : clamp(from.w + (from.x - e.clientX), from.l.minW, from.l.maxW));
    const up = () => {
      panel.classList.remove('resizing');
      grip.removeEventListener('pointermove', move);
      save();
    };
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up, { once: true });
    grip.addEventListener('pointercancel', up, { once: true });
  });

  // The same with the keyboard: arrows change the height (and, on wider screens, left and right the width).
  grip.addEventListener('keydown', (event) => {
    const { h, w, l } = size();
    const keys = {
      ArrowUp: [h + STEP, w], ArrowDown: [h - STEP, w], Home: [l.minH, w], End: [l.maxH, w],
      ArrowLeft: [h, w + STEP], ArrowRight: [h, w - STEP],
    };
    if (!(event.key in keys) || (PHONE.matches && (event.key === 'ArrowLeft' || event.key === 'ArrowRight'))) return;
    event.preventDefault();
    const [nh, nw] = keys[event.key];
    resize(clamp(nh, l.minH, l.maxH), PHONE.matches ? undefined : clamp(nw, l.minW, l.maxW));
    save();
  });

  launcher.addEventListener('click', open);
  $('talk-min').addEventListener('click', minimise);
  panel.addEventListener('keydown', (event) => { if (event.key === 'Escape') minimise(); });
  // The page (and, on the Money Hub, the tab) the customer is on is the conversation's context: the app calls
  // refresh() when it changes, and a click anywhere may change a tab.
  document.addEventListener('click', () => setTimeout(context));
  PHONE.addEventListener('change', apply);
  window.addEventListener('resize', apply);

  launcher.hidden = false;
  context();
  apply();

  return {
    open,
    minimise,
    hide() { panel.hidden = true; launcher.hidden = false; launcher.setAttribute('aria-expanded', 'false'); context(); apply(); },
    refresh: context,
    live(kind) {
      liveKind = kind || '';
      startedOn = kind ? pageContext() : null;
      context();
    },
  };
}
