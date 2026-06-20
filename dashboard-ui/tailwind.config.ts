import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: '#0d0b12',
        'card-bg': '#171421',
        'card-border': '#2b2736',
        'text-primary': '#e0dde7',
        'text-muted': '#88829b',
        'accent-blue': '#689df2',
        'accent-green': '#53c677',
        'accent-red': '#f1576b',
        'accent-yellow': '#dcaf55',
        'accent-orange': '#ef7e47',
        'accent-purple': '#ae91f0',
        'accent-cyan': '#4cc6bd',
        'grid-line': '#1f1b2a',
      },
    },
  },
} satisfies Config
