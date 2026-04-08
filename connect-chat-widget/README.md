# connect-chat-widget

A React (Vite) app that embeds the Amazon Connect Chat Widget on the home page.

## Quick start

```bash
cd connect-chat-widget
npm install
npm run dev          # http://localhost:4000
```

## CORS / CSP notes

The widget loads an external script and opens an iframe from
`https://conversationalbot.my.connect.aws`. Two things must be correct for it
to work:

### 1. Content-Security-Policy (this app)

`index.html` contains a `<meta http-equiv="Content-Security-Policy">` tag that
permits the Connect origin for `script-src`, `frame-src`, and `connect-src`.
If you see CSP errors in the browser console, adjust that tag.

### 2. Approved origins (Amazon Connect console)

The Connect widget will **refuse to initialise** unless the page origin is on
the **Approved origins** allowlist in your Connect instance settings:

1. AWS Console → Amazon Connect → your instance
2. Left nav → **Approved origins**
3. Add: `http://localhost:4000` (for dev) and your production URL

Without this step the widget silently fails to load.

## Configuration

The widget configuration lives in `src/components/ConnectChatWidget.jsx`:

| Setting | Value |
|---|---|
| Script URL | `https://conversationalbot.my.connect.aws/connectwidget/static/amazon-connect-chat-interface-client.js` |
| Widget instance ID | `9ed4221c-dc38-4ab2-a475-d2a8209c0d6a` |
| Snippet ID | see `ConnectChatWidget.jsx` |
| Brand colour | `#123456` |

## Build for production

```bash
npm run build        # output in dist/
npm run preview      # preview the built app on :5000
```
