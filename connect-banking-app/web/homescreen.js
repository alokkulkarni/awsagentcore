// "Add to Home Screen" on a phone or tablet. The phone saves the address as it is, and the app wipes the link's
// secret from the address as soon as it opens (lib.js), so a shortcut made the usual way opens with no link. And on
// an iPhone a Home Screen app has its own storage, so it can't find the secret this browser kept either.
// So: on the customer's request only, put the secret back in the address (lib.js showLink), show the steps, and wipe
// it again when they close the steps, change page, or after two minutes. Not shown once opened from the Home Screen.
import { $, hideLink, showLink } from './lib.js';

const standalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const touch = () => window.matchMedia('(pointer: coarse)').matches;
// iPadOS reports itself as a Mac: a Mac with a touch screen is an iPad.
const apple = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

export function setupHomeScreen() {
  const button = $('home-screen');
  const dialog = $('home-screen-steps');
  if (!button || !dialog || standalone() || !touch()) return;
  $('home-screen-apple').hidden = !apple();
  $('home-screen-other').hidden = apple();
  button.hidden = false;
  button.addEventListener('click', () => {
    if (!showLink()) return;
    dialog.showModal();
  });
  dialog.addEventListener('close', hideLink);
  $('home-screen-done').addEventListener('click', () => dialog.close());
}

export function hideHomeScreen() {
  const button = $('home-screen');
  if (button) button.hidden = true;
  hideLink();
}
