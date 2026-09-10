/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // tokens cyberpunk (mesmos do admin/dashboard atuais)
        bg: "#030509",
        card: "#0a1420",
        "card-hover": "#0e1c2e",
        text: "#d7e6f5",
        muted: "#5b7a94",
        accent: "#00d9ff",
        accent2: "#2f6fff",
        border: "#123049",
        ok: "#2be07a",
        warn: "#ffb020",
        danger: "#ff3d6e",
      },
      fontFamily: {
        display: ['"Chakra Petch"', "system-ui", "sans-serif"],
        body: ['"Rajdhani"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 12px rgba(0,217,255,.25)",
        "glow-lg": "0 0 22px rgba(0,217,255,.4)",
      },
    },
  },
  plugins: [],
};
