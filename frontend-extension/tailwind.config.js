/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './side_panel.html',
    './src/**/*.{ts,tsx}',
    '../frontend/App.tsx',
    '../frontend/components/**/*.{ts,tsx}',
    '../frontend/services/**/*.{ts,tsx}',
    '../frontend/utils/**/*.{ts,tsx}',
    '../frontend/*.{ts,tsx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
