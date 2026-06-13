import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './hooks/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans:    ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono:    ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        tech:    ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        display: ['var(--font-display)', 'Cinzel', 'Georgia', 'serif'],
      },
      colors: {
        spell: {
          g0: '#000000', g05: '#0a0a0a', g1: '#111111', g2: '#232323',
          g3: '#343434', g4: '#464646', g5: '#575757', g6: '#696969', g7: '#7a7a7a',
        },
        blood: { DEFAULT: '#8c2731', text: '#b85560', bg: '#150b0c' },
        surface: { base: '#000000', raised: '#0a0a0a', card: '#111111', overlay: '#161616' },
        edge: {
          DEFAULT: '#232323', subtle: 'rgba(35,35,35,0.6)',
          bright: '#343434', silver: 'rgba(255,255,255,0.12)',
        },
        ink: {
          primary: '#e8e8e8', secondary: '#c4c4c4',
          muted: '#696969', ghost: '#464646', hot: '#ffffff',
        },
        dot: {
          pending: '#343434', diarized: '#575757', tts: '#696969',
          complete: '#c4c4c4', error: '#b85560', running: '#ffffff',
        },
      },
      keyframes: {
        breathe:      { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.35' } },
        glowpulse: {
          '0%, 100%': { boxShadow: '0 0 26px rgba(255,255,255,0.07)' },
          '50%':      { boxShadow: '0 0 48px rgba(255,255,255,0.14)' },
        },
        'fade-in':  { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        'slide-up': { from: { opacity: '0', transform: 'translateY(10px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        flicker: {
          '0%, 91%, 94%, 97%, 100%': { opacity: '1' },
          '92%, 95%': { opacity: '0.75' }, '96%': { opacity: '0.85' },
        },
        'toast-in': { from: { opacity: '0', transform: 'translateX(16px)' }, to: { opacity: '1', transform: 'translateX(0)' } },
        equalize:   { '0%, 100%': { transform: 'scaleY(0.3)' }, '50%': { transform: 'scaleY(1)' } },
      },
      animation: {
        breathe:    'breathe 2.4s ease-in-out infinite',
        glowpulse:  'glowpulse 3.2s ease-in-out infinite',
        'fade-in':  'fade-in 0.2s ease-out',
        'slide-up': 'slide-up 0.25s ease-out',
        flicker:    'flicker 7s ease-in-out infinite',
        'toast-in': 'toast-in 0.22s ease-out',
        equalize:   'equalize 0.9s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

export default config
