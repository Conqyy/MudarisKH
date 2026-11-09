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
        // Shared RGB-triplet palette with opacity modifiers such as bg-sage/10.
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
        control: "rgb(var(--c-control) / <alpha-value>)",
        depth: "rgb(var(--c-depth) / <alpha-value>)",
        danger: "rgb(var(--c-danger) / <alpha-value>)",
      },
      fontFamily: {
        // Direct font names — match prototype exactly
        serif: ['Manrope', 'sans-serif'],
        sans: ['Manrope', 'sans-serif'],
        mono: ['Manrope', 'sans-serif'],
      },
      boxShadow: {
        soft: "0 2px 8px rgb(var(--c-shadow) / .04)",
        lift: "0 8px 32px rgb(var(--c-shadow) / .08)",
      },
      animation: {
        "spin-slow": "spin 1.2s linear infinite",
        "pulse-soft": "pulse 2s infinite",
        "fade-in": "fadeIn 0.18s cubic-bezier(0.23,1,0.32,1)",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0", transform: "translateY(3px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
