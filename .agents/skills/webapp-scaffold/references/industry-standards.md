# Webapp Scaffold Industry Standards

## Security and application standards

- OWASP Top 10 — https://owasp.org/www-project-top-ten/
- OWASP Web Security Testing Guide — https://owasp.org/www-project-web-security-testing-guide/
- WCAG 2.1 — https://www.w3.org/TR/WCAG21/
- React security and CSS style handling — https://react.dev/reference/react-dom/components/common#applying-css-styles
- Vite env vars — https://vitejs.dev/guide/env-and-mode
- CloudFront security — https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/secure-connections-supported-ciphers.html
- CSP reference (MDN) — https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP
- Content-Security-Policy quick reference — https://content-security-policy.com/
- WCAG contrast checker — https://webaim.org/resources/contrastchecker/
- agentskills.io — https://agentskills.io

## Why these matter

| Standard | Relevance |
| --- | --- |
| OWASP Top 10 | Baseline web risk model for secure defaults such as CSP, no secrets in source, and dependency hygiene. |
| OWASP WSTG | Practical testing guidance for validation after scaffolding. |
| WCAG 2.1 | Accessibility baseline for colour contrast, keyboard focus, labels, and semantic structure. |
| React docs | Safe DOM, CSS, and JSX patterns for a production React frontend. |
| Vite docs | Canonical guidance for env handling and build/runtime behaviour. |
| CloudFront docs | TLS posture and HTTPS-only delivery expectations for public hosting. |
| CSP references | Implementation guidance for secure client-side asset loading. |
| agentskills.io | Portable skill packaging format and conventions. |

## Optional Chat Provider References
| Provider | Documentation |
|----------|--------------|
| Amazon Connect | https://docs.aws.amazon.com/connect/latest/adminguide/add-chat-to-website.html |
| Intercom | https://developers.intercom.com/installing-intercom/docs/basic-javascript |
| Zendesk Web Widget | https://developer.zendesk.com/documentation/classic-web-widget-sdks/web-widget/getting-started/ |
| Crisp | https://help.crisp.chat/en/article/how-to-add-crisp-chat-to-your-website-de9cpf/ |
| Freshchat | https://developers.freshchat.com/web-sdk-reference/ |
