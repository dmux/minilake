# `site/` — the project website

The landing page published to GitHub Pages at <https://dmux.github.io/minilake/>.

It is a single self-contained `index.html` (inline CSS and JS, no build step, no
dependencies) plus the images in `assets/`. Edit it and push to `main`; the
`Pages` workflow uploads this directory as-is.

Preview it locally with any static server:

```bash
python3 -m http.server 4599 --directory site
# http://localhost:4599
```

## Theming

The page ships light and dark. Colours live as CSS custom properties on `:root`;
dark redefines only the tokens that change, in two places that must stay in
sync — `@media (prefers-color-scheme:dark)` (guarded so an explicit light choice
still wins, and the only rule that applies without JS) and `[data-theme="dark"]`
(what the toggle sets). A script in `<head>` stamps `data-theme` before the
first paint, so switching never flashes; the choice is kept in `localStorage`
under `minilake-theme`, and while nothing is stored the OS setting leads.

When adding colour, use a token — a literal hex is only correct for something
that sits on a permanently dark surface (`.band`, `.cta`, `.window`, and the
white buttons on them). The architecture diagram is themed the same way: its
styles live in the main stylesheet under `.arch svg`, not inside the SVG, since
an inline `<svg><style>` applies to the whole document.

## Assets

| File | What it is |
|---|---|
| `assets/minilake-logo.png` | `minilake_logo.png` from the repo root, background knocked out and trimmed |
| `assets/og.png` | 1200×630 social preview card (`og:image`) |
| `assets/favicon-32.png`, `favicon-64.png`, `apple-touch-icon.png` | Icons derived from the same mark |

`.nojekyll` keeps GitHub from running the files through Jekyll.

Content on the page is drawn from `README.md`, `FEATURES.md` and `docs/` — when a
feature's status changes there, update the "Coverage" table here too.
