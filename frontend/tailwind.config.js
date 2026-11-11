/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Design tokens shared by every workspace; see docs/UI_NAVIGATION.md.
        nv: {
          canvas: '#0B0D10',
          chrome: '#0E1115',
          panel: '#12151A',
          raised: '#161A20',
          hover: '#1A1E25',
          active: '#262C36',
          line: '#1C2027',
          edge: '#2A303A',
          'edge-strong': '#3A424E',
          muted: '#9AA3AE',
          ink: '#E6E8EB',
          'ink-strong': '#F2F4F6',
          accent: '#FF8533',
          'accent-soft': '#FFB27A',
          'accent-ink': '#1F0D02',
          ok: '#46D19A',
          'ok-ink': '#7FE0B8',
          warn: '#F2B544',
          'warn-ink': '#F2C46D',
          err: '#F27C7C',
          'err-ink': '#F5A3A3',
          series2: '#B49CFB',
          series3: '#4CC9F0',
          reference: '#C4CAD2',
        },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', '"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      screens: {
        wide: '1600px',
      },
    },
  },
  plugins: [],
};
