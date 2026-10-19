# HUDA client

React 19 + Vite + Tailwind v4 + react-leaflet. See the [root README](../README.md) to run it.

- `VITE_USE_MOCKS=true` runs against the in-memory mock API in `src/lib/mocks.js` (no Clerk, no backend).
- Risk levels are defined only in `src/lib/levels.js` and shown through `<RiskBadge>`: colour + icon + text.
- All user-visible strings live in `src/lib/strings.js` (EN + BM).
