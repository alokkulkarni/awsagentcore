#!/usr/bin/env python3
"""Generate Vitest and Playwright tests for a scaffolded webapp."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Sequence

TEST_DEV_DEPENDENCIES = {
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/user-event": "^14.5.0",
    "@vitejs/plugin-react": "^4.3.1",
    "@playwright/test": "^1.45.0",
    "@axe-core/playwright": "^4.9.0",
    "vitest": "^2.0.0",
    "@vitest/coverage-v8": "^2.0.0",
    "jsdom": "^24.0.0",
}

TEST_SCRIPTS = {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage",
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate unit and E2E tests for a scaffolded webapp.")
    parser.add_argument("project_dir", help="Path to the generated webapp directory.")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip Playwright config and E2E tests.")
    parser.add_argument("--skip-unit", action="store_true", help="Skip Vitest config and unit tests.")
    return parser.parse_args(argv)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def detect_port(project_dir: Path) -> int:
    vite_config = (project_dir / "vite.config.js").read_text(encoding="utf-8") if (project_dir / "vite.config.js").exists() else ""
    match = re.search(r"server:\s*\{\s*port:\s*(\d+)", vite_config)
    if match:
        return int(match.group(1))
    return 4001


def detect_metadata(project_dir: Path) -> Dict[str, str]:
    package_json = read_json(project_dir / "package.json") if (project_dir / "package.json").exists() else {}
    index_html = (project_dir / "index.html").read_text(encoding="utf-8") if (project_dir / "index.html").exists() else ""
    title_match = re.search(r"<title>(.*?)</title>", index_html, re.DOTALL)
    title = title_match.group(1).strip() if title_match else package_json.get("name", "webapp")
    return {
        "project_name": str(package_json.get("name", title)),
        "page_title": title,
    }


def merge_package_json(package_data: Dict[str, Any]) -> Dict[str, Any]:
    package_data.setdefault("scripts", {})
    package_data.setdefault("devDependencies", {})
    for name, command in TEST_SCRIPTS.items():
        package_data["scripts"][name] = command
    for name, version in TEST_DEV_DEPENDENCIES.items():
        package_data["devDependencies"][name] = version
    return package_data


def build_vitest_config() -> str:
    return """import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.js'],
    include: ['./src/__tests__/**/*.{test,spec}.{js,jsx}'],
    exclude: ['./e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      thresholds: { statements: 80, branches: 80, functions: 80, lines: 80 },
    },
  },
});
"""


def build_playwright_config(port: int) -> str:
    return f"""import {{ defineConfig, devices }} from '@playwright/test';

export default defineConfig({{
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [['html', {{ outputFolder: 'playwright-report' }}]],
  use: {{ baseURL: 'http://localhost:{port}', trace: 'on-first-retry' }},
  projects: [
    {{ name: 'chromium', use: {{ ...devices['Desktop Chrome'] }} }},
    {{ name: 'Mobile Chrome', use: {{ ...devices['Pixel 7'] }} }},
    {{ name: 'Mobile Safari', use: {{ ...devices['iPhone 14'] }} }},
    {{ name: 'iPad', use: {{ ...devices['iPad (gen 7)'] }} }},
  ],
  webServer: {{ command: 'npm run dev', url: 'http://localhost:{port}', reuseExistingServer: !process.env.CI }},
}});
"""


def build_setup() -> str:
    return """import '@testing-library/jest-dom';

window.__chatConfig = { provider: 'custom', config: { script_url: 'https://example.com/widget.js' } };
globalThis.MutationObserver = class {
  constructor(cb) { this.cb = cb; }
  observe() {}
  disconnect() {}
};
"""


def build_header_test() -> str:
    return """import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Header } from '../components/Header.jsx';

describe('Header', () => {
  const props = {
    brandName: 'Test Brand',
    navItems: [
      { label: 'Home', href: '#home' },
      { label: 'Support', href: '#support' },
    ],
    primaryCtaLabel: 'Get started',
    secondaryCtaLabel: 'Contact us',
    primaryHref: '#get-started',
    secondaryHref: '#contact',
    logoMode: 'text',
    logoText: 'TB',
    logoSrc: '',
  };

  it('renders the logo, nav links, and CTA buttons', () => {
    render(<Header {...props} />);

    expect(screen.getByRole('link', { name: /test brand home/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Home' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Support' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Get started' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Contact us' })).toBeVisible();
  });

  it('matches the header snapshot', () => {
    const { container } = render(<Header {...props} />);
    expect(container.firstChild).toMatchSnapshot();
  });
});
"""


def build_hero_test() -> str:
    return """import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Hero } from '../components/Hero.jsx';

describe('Hero', () => {
  const props = {
    headline: 'Launch with confidence',
    subtitle: 'Build accessible, secure experiences quickly.',
    primaryCtaLabel: 'Get started',
    secondaryCtaLabel: 'Learn more',
    primaryHref: '#get-started',
    secondaryHref: '#learn-more',
    brandName: 'Test Brand',
    vertical: 'generic',
    stats: [
      { value: '24/7', label: 'Support' },
      { value: 'WCAG', label: 'Accessible' },
      { value: 'Vite', label: 'Fast' },
    ],
  };

  it('renders the hero content and CTA buttons', () => {
    render(<Hero {...props} />);

    expect(screen.getByRole('heading', { name: /launch with confidence/i })).toBeVisible();
    expect(screen.getByText(/build accessible, secure experiences quickly/i)).toBeVisible();
    expect(screen.getByRole('link', { name: 'Get started' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Learn more' })).toBeVisible();
  });

  it('exposes an accessible hero actions landmark', () => {
    render(<Hero {...props} />);
    expect(screen.getByRole('navigation', { name: /hero actions/i })).toBeInTheDocument();
  });
});
"""


def build_footer_test() -> str:
    return """import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Footer } from '../components/Footer.jsx';

describe('Footer', () => {
  it('renders the supplied copyright text', () => {
    render(
      <Footer
        brandName="Test Brand"
        footerText="Custom footer copy"
        copyrightEntity="Test Brand"
        navItems={[{ label: 'Home', href: '#home' }]}
      />,
    );

    expect(screen.getByText(/custom footer copy/i)).toBeVisible();
    expect(screen.getByText(/© 2026 test brand/i)).toBeVisible();
  });
});
"""


def build_chat_widget_test() -> str:
    return """import { render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatWidget from '../components/ChatWidget.jsx';

describe('ChatWidget', () => {
  afterEach(() => {
    document.head.innerHTML = '';
    document.body.innerHTML = '';
    window.__chatConfig = { provider: 'custom', config: { script_url: 'https://example.com/widget.js' } };
    vi.restoreAllMocks();
  });

  it('renders null', () => {
    const { container } = render(<ChatWidget enabled={false} provider="none" config={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('loads a provider script when enabled', async () => {
    const appendSpy = vi.spyOn(document.head, 'appendChild').mockImplementation((node) => {
      if (typeof node.onload === 'function') {
        queueMicrotask(() => node.onload(new Event('load')));
      }
      return node;
    });

    render(<ChatWidget enabled provider="custom" config={{ script_url: 'https://example.com/widget.js' }} />);

    await waitFor(() => expect(appendSpy).toHaveBeenCalled());
  });

  it('disconnects any observer during cleanup', async () => {
    const disconnect = vi.fn();
    globalThis.MutationObserver = class {
      constructor(cb) { this.cb = cb; }
      observe() {}
      disconnect() { disconnect(); }
    };

    vi.spyOn(document.head, 'appendChild').mockImplementation((node) => {
      if (typeof node.onload === 'function') {
        queueMicrotask(() => node.onload(new Event('load')));
      }
      return node;
    });

    const { unmount } = render(
      <ChatWidget
        enabled
        provider="amazon-connect"
        config={{
          script_url: 'https://example.com/widget.js',
          bot_display_name: 'Assistant',
          agent_display_name: 'Support',
        }}
      />,
    );

    await waitFor(() => expect(document.getElementById('chat-widget-script')).toBeTruthy());
    unmount();

    expect(disconnect).toHaveBeenCalledOnce();
  });
});
"""


def build_app_test() -> str:
    return """import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from '../App.jsx';

describe('App', () => {
  it('renders the header, hero, and footer without console errors', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<App />);

    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    expect(consoleError).not.toHaveBeenCalled();

    consoleError.mockRestore();
  });
});
"""


def build_homepage_spec(page_title: str) -> str:
    return f"""import {{ test, expect }} from '@playwright/test';

test('loads the homepage with its core navigation and hero content', async ({{ page }}) => {{
  await page.goto('/');

  await expect(page).toHaveTitle('{page_title}');
  await expect(page.getByRole('heading', {{ level: 1 }})).toBeVisible();
  await expect(page.getByRole('navigation', {{ name: /primary navigation/i }})).toBeVisible();
  await expect(page.getByRole('link', {{ name: /get started|shop now|contact/i }}).first()).toBeVisible();
}});
"""


def build_chat_widget_spec(provider: str) -> str:
    return f"""import {{ test, expect }} from '@playwright/test';

test('exposes runtime chat config when the widget is enabled', async ({{ page }}) => {{
  await page.goto('/');

  const chatConfig = await page.evaluate(() => window.__chatConfig || null);
  expect(chatConfig).not.toBeNull();
  expect(chatConfig?.provider).toBe('{provider}');
}});
"""


def build_mobile_spec() -> str:
    return """import { test, expect } from '@playwright/test';

test('keeps the hero visible and collapses navigation on iPhone 13', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  await expect(page.getByRole('button', { name: /toggle navigation/i })).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('keeps the layout stable on iPad', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.goto('/');

  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('shows the full navigation on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/');

  await expect(page.getByRole('navigation', { name: /primary navigation/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /toggle navigation/i })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
"""


def build_accessibility_spec() -> str:
    return """import AxeBuilder from '@axe-core/playwright';
import { test, expect } from '@playwright/test';

test('has no WCAG 2.1 AA accessibility violations', async ({ page }) => {
  await page.goto('/');

  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(results.violations).toEqual([]);
});

test('ensures all images have alt text', async ({ page }) => {
  await page.goto('/');

  const allHaveAlt = await page.locator('img').evaluateAll((images) => images.every((img) => img.getAttribute('alt')?.trim()));
  expect(allHaveAlt).toBe(true);
});

test('supports a predictable focus order', async ({ page }) => {
  await page.goto('/');

  await page.keyboard.press('Tab');
  const firstFocus = await page.evaluate(() => document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent || '');
  await page.keyboard.press('Tab');
  const secondFocus = await page.evaluate(() => document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent || '');

  expect(firstFocus).not.toEqual('');
  expect(secondFocus).not.toEqual(firstFocus);
});

test('has no colour contrast violations', async ({ page }) => {
  await page.goto('/');

  const results = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
  expect(results.violations).toEqual([]);
});
"""


def build_test_files(
    port: int,
    page_title: str,
    chat_enabled: bool = False,
    chat_provider: str = 'none',
    skip_unit: bool = False,
    skip_e2e: bool = False,
) -> Dict[str, str]:
    files: Dict[str, str] = {}
    if not skip_unit:
        files.update(
            {
                'vitest.config.js': build_vitest_config(),
                'src/__tests__/setup.js': build_setup(),
                'src/__tests__/Header.test.jsx': build_header_test(),
                'src/__tests__/Hero.test.jsx': build_hero_test(),
                'src/__tests__/Footer.test.jsx': build_footer_test(),
                'src/__tests__/App.test.jsx': build_app_test(),
            }
        )
        if chat_enabled:
            files['src/__tests__/ChatWidget.test.jsx'] = build_chat_widget_test()
    if not skip_e2e:
        files.update(
            {
                'playwright.config.js': build_playwright_config(port),
                'e2e/homepage.spec.js': build_homepage_spec(page_title),
                'e2e/mobile.spec.js': build_mobile_spec(),
                'e2e/accessibility.spec.js': build_accessibility_spec(),
            }
        )
        if chat_enabled:
            files['e2e/chat-widget.spec.js'] = build_chat_widget_spec(chat_provider)
    return files


def scaffold_tests(project_dir: Path, skip_unit: bool = False, skip_e2e: bool = False) -> int:
    package_path = project_dir / 'package.json'
    if not package_path.exists():
        raise SystemExit(f'[ERROR] package.json not found in {project_dir}')

    package_data = merge_package_json(read_json(package_path))
    write_text(package_path, json.dumps(package_data, indent=2) + '\n')

    port = detect_port(project_dir)
    metadata = detect_metadata(project_dir)
    chat_widget = project_dir / 'src' / 'components' / 'ChatWidget.jsx'
    chat_enabled = chat_widget.exists()
    chat_provider = 'none'
    if chat_enabled:
        app_text = (project_dir / 'src' / 'App.jsx').read_text(encoding='utf-8') if (project_dir / 'src' / 'App.jsx').exists() else ''
        match = re.search(r"provider[\"']?\s*:\s*[\"']([^\"']+)[\"']", app_text)
        if match:
            chat_provider = match.group(1)

    for relative_path, content in build_test_files(
        port,
        metadata['page_title'],
        chat_enabled=chat_enabled,
        chat_provider=chat_provider,
        skip_unit=skip_unit,
        skip_e2e=skip_e2e,
    ).items():
        write_text(project_dir / relative_path, content)

    print(f'Generated test assets in {project_dir}')
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return scaffold_tests(Path(args.project_dir).expanduser().resolve(), skip_unit=args.skip_unit, skip_e2e=args.skip_e2e)


if __name__ == '__main__':
    raise SystemExit(main())
