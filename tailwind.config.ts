import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // RGB-triplet CSS variables (set in globals.css) so the whole palette
        // swaps for dark mode while opacity modifiers (e.g. bg-sage/10) keep
        // working via <alpha-value>.
        bg: "rgb(var(--c-bg) / <alpha-value>)",
        "bg-alt": "rgb(var(--c-bg-alt) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        "ink-soft": "rgb(var(--c-ink-soft) / <alpha-value>)",
        "ink-mute": "rgb(var(--c-ink-mute) / <alpha-value>)",
        accent: "rgb(var(--c-accent) / <alpha-value>)",
        "accent-soft": "rgb(var(--c-accent-soft) / <alpha-value>)",
        gold: "rgb(var(--c-gold) / <alpha-value>)",
        sage: "rgb(var(--c-sage) / <alpha-value>)",
        paper: "rgb(var(--c-paper) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
      },
      fontFamily: {
        // Direct font names — match prototype exactly
        serif: ['Fraunces', 'serif'],
        sans: ['"IBM Plex Sans"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      boxShadow: {
        soft: "0 1px 3px rgba(26,24,20,0.04), 0 8px 24px rgba(26,24,20,0.06)",
        lift: "0 4px 12px rgba(26,24,20,0.08), 0 20px 40px rgba(26,24,20,0.1)",
      },
      animation: {
        "spin-slow": "spin 1.2s linear infinite",
        "pulse-soft": "pulse 2s infinite",
        "fade-in": "fadeIn 0.5s ease-out",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;