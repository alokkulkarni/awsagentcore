import typography from '@tailwindcss/typography';

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        connect: {
          50: '#eff6ff',
          100: '#dbeafe',
          400: '#60a5fa',
          500: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },
      },
      boxShadow: {
        panel: '0 20px 45px -28px rgba(15, 23, 42, 0.45)',
      },
      keyframes: {
        'border-pulse': {
          '0%, 100%': { borderColor: 'rgba(99,102,241,0.3)', boxShadow: '0 0 12px rgba(99,102,241,0.12)' },
          '50%':        { borderColor: 'rgba(99,102,241,0.7)', boxShadow: '0 0 22px rgba(99,102,241,0.30)' },
        },
      },
      animation: {
        'pulse-border': 'border-pulse 2s ease-in-out infinite',
      },
      typography: ({ theme }) => ({
        // Custom dark-mode prose for the chat bubbles
        chat: {
          css: {
            '--tw-prose-body': theme('colors.slate[100]'),
            '--tw-prose-headings': theme('colors.white'),
            '--tw-prose-bold': theme('colors.white'),
            '--tw-prose-links': theme('colors.blue[400]'),
            '--tw-prose-code': theme('colors.sky[300]'),
            '--tw-prose-bullets': theme('colors.slate[400]'),
            '--tw-prose-counters': theme('colors.slate[400]'),
            '--tw-prose-hr': theme('colors.slate[700]'),
            '--tw-prose-th-borders': theme('colors.slate[600]'),
            '--tw-prose-td-borders': theme('colors.slate[700]'),
            // Force bold/strong to always use the inherited text colour so it
            // can't be overridden to near-black by the base `prose` cascade.
            strong: { color: 'inherit', fontWeight: '700' },
            b: { color: 'inherit', fontWeight: '700' },
            // react-markdown wraps loose list items in <p> tags which adds
            // paragraph margins inside list items — remove them.
            'li > p': { marginTop: '0', marginBottom: '0' },
            'li > p:first-child': { marginTop: '0' },
            'li > p:last-child': { marginBottom: '0' },
            // Tighten up spacing inside chat bubbles
            p: { marginTop: '0.35rem', marginBottom: '0.35rem' },
            ul: { marginTop: '0.35rem', marginBottom: '0.35rem' },
            ol: { marginTop: '0.35rem', marginBottom: '0.35rem' },
            li: { marginTop: '0.1rem', marginBottom: '0.1rem' },
            h1: { fontSize: '1rem', marginTop: '0.75rem', marginBottom: '0.2rem' },
            h2: { fontSize: '0.95rem', marginTop: '0.6rem', marginBottom: '0.2rem' },
            h3: { fontSize: '0.875rem', marginTop: '0.5rem', marginBottom: '0.15rem' },
            table: { fontSize: '0.8rem' },
            'th, td': { padding: '0.35rem 0.6rem' },
            hr: { marginTop: '0.75rem', marginBottom: '0.75rem' },
            // Strip default quote styling — not needed in chat
            blockquote: { borderLeftColor: theme('colors.blue[500]'), fontStyle: 'normal' },
            code: { fontWeight: '400' },
            'code::before': { content: '""' },
            'code::after': { content: '""' },
          },
        },
      }),
    },
  },
  plugins: [typography],
};
