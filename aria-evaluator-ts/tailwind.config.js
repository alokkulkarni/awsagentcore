/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/ui/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#0D2A66',
          light: '#1a3f8f',
        },
      },
    },
  },
  plugins: [],
};
