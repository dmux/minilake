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

## Assets

| File | What it is |
|---|---|
| `assets/minilake-logo.png` | `minilake_logo.png` from the repo root, background knocked out and trimmed |
| `assets/og.png` | 1200×630 social preview card (`og:image`) |
| `assets/favicon-32.png`, `favicon-64.png`, `apple-touch-icon.png` | Icons derived from the same mark |

`.nojekyll` keeps GitHub from running the files through Jekyll.

Content on the page is drawn from `README.md`, `FEATURES.md` and `docs/` — when a
feature's status changes there, update the "Coverage" table here too.
