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
        bg: "#f7f3ec",
        "bg-alt": "#efe9dd",
        ink: "#1a1814",
        "ink-soft": "#4a4640",
        "ink-mute": "#8a847a",
        accent: "#c8472f",
        "accent-soft": "#e8a594",
        gold: "#b8923a",
        sage: "#6b7d5b",
        paper: "#fffbf3",
        line: "#d8d0c0",
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