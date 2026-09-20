import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["var(--font-display)", "Rajdhani", "sans-serif"],
        sans: ["var(--font-sans)", "IBM Plex Sans", "sans-serif"],
        mono: ["var(--font-mono)", "IBM Plex Mono", "monospace"],
      },
      colors: {
        ink: {
          950: "#05070c",
          900: "#080c14",
          800: "#0c1422",
          700: "#121c2e",
          600: "#1a2740",
        },
        signal: {
          cyan: "#3ee0ff",
          amber: "#ffb020",
          rose: "#ff4d6d",
          lime: "#b6ff4a",
          violet: "#c084fc",
          ice: "#d8f4ff",
        },
      },
      boxShadow: {
        glow: "0 0 40px color-mix(in srgb, var(--phase) 35%, transparent)",
      },
    },
  },
  plugins: [],
};

export default config;
