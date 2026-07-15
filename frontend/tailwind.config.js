/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#111111',
        accent: '#E8450A',
        'accent-dark': '#C93A08',
        win: '#2E9E5B',
        loss: '#D23B3B',
        line: '#E6E6E6',
        muted: '#6B6B6B',
        // Dark landing theme (graphite product look)
        graphite: {
          950: '#0B0C0E',
          900: '#121316',
          850: '#17181C',
          800: '#1E2025',
        },
        'line-dark': '#26292F',
        steel: {
          100: '#EDEEF0',
          400: '#9BA0A8',
          500: '#7C818A',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
        display: ['"Barlow Condensed"', 'Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
