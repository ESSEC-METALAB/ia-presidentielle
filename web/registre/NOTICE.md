# Bundled third-party files

The register works without any network access: everything it loads is in this folder.

| Path | What | Licence |
|---|---|---|
| `support.js`, `image-slot.js` | Runtime and components of the site prototype ("IA 2027 — Registre" v3) | Provided with the prototype |
| `silk-flag.js` | The waving flag. Its header says it ports the "Silk" shader of React Bits (github.com/DavidHDev/react-bits) to plain WebGL | React Bits is published under MIT, or MIT with the Commons Clause depending on the version; **to confirm before publication**. The Commons Clause forbids selling the software, not using it on a non-commercial site |
| `vendor/react.production.min.js`, `vendor/react-dom.production.min.js` | React 18.3.1, byte-identical to the unpkg files the runtime pins (same SHA-384) | MIT, `vendor/LICENSE-react` |
| `vendor/gsap.min.js` | GSAP 3.12.5 | GreenSock standard "no charge" licence, https://gsap.com/standard-license |
| `fonts/*.woff2`, `fonts/fonts.css` | Space Grotesk, Spectral, JetBrains Mono (latin and latin-ext subsets) and Material Symbols Sharp, from Google Fonts | SIL Open Font License 1.1, with each family's copyright line: `fonts/licenses/OFL-*.txt`; Material Symbols: Apache License 2.0, `fonts/licenses/LICENSE-material-symbols-apache-2.0.txt` |

`index.html` loads React and ReactDOM from `vendor/` before `support.js`; the runtime
downloads them only when `window.React` is missing, so `support.js` itself is unchanged.
Do not use the runtime's `window.__resources` hook instead: it switches the runtime to
"bundled" mode, which skips re-reading the page's template, and the barometer's table rows
then never render (measured).

`.image-slots.state.json` is the prototype's portrait store, empty: the cards show
initials. Portraits, if ever added, are shown in black and white at one format for every
candidate (methodology, "Égalité de traitement").

To refresh a font: request the same Google Fonts CSS2 URL with a recent browser's
User-Agent, keep the latin and latin-ext `@font-face` blocks, download their `woff2`
files here and point `fonts.css` at them.
