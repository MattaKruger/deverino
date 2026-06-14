import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: '#0d1117',
        'card-bg': '#161b22',
        'card-border': '#30363d',
        'text-primary': '#c9d1d9',
        'text-muted': '#8b949e',
        'accent-blue': '#58a6ff',
        'accent-green': '#3fb950',
        'accent-red': '#f85149',
        'accent-yellow': '#d29922',
        'accent-orange': '#d97706',
        'accent-purple': '#a371f7',
        'accent-cyan': '#39d2c0',
        'grid-line': '#21262d',
      },
    },
  },
} satisfies Config
