export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          cyan: '#22d3ee',
          indigo: '#818cf8',
          emerald: '#34d399',
          rose: '#fb7185',
          amber: '#fbbf24',
        },
      },
      boxShadow: {
        panel: '0 20px 45px -28px rgba(15, 23, 42, 0.55)',
      },
      keyframes: {
        'soft-pulse': {
          '0%, 100%': { opacity: '0.55', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.05)' },
        },
      },
      animation: {
        'soft-pulse': 'soft-pulse 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
