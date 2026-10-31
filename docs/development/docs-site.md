# Build & host these docs

The site uses VitePress. Markdown lives in `docs/`; theme and navigation live in `docs/.vitepress/`. Building the documentation does not install or run the Python framework.

## Preview locally

Use Node.js 22+ and npm, from the repository root:

```bash
npm ci
npm run docs:dev
```

Open the URL printed by VitePress, normally `http://127.0.0.1:5173/FlashRSI/`. Navigation, code copying, local full-text search, and mobile menus work without external services. Search is populated from rendered Markdown; production builds include its index. Historical plans and the duplicate Markdown overview remain browsable from the reference index but are excluded from search.

## Build static files

```bash
npm run docs:build
npm run docs:check
npm run docs:preview
```

Open `http://127.0.0.1:4173/FlashRSI/`. The deployable output is `docs/.vitepress/dist/`. Serve it over HTTP; interactive features require JavaScript modules and should not be opened through `file://`.

The default base is `/FlashRSI/`, matching the current GitHub repository. To build for a custom domain or another repository, set the base path:

```bash
DOCS_BASE=/ npm run docs:build
DOCS_BASE=/another-repo/ npm run docs:build
```

The base must start and end with `/`. For GitHub Pages, the prepared workflow selects the base from the repository name, including `/` for a user or organization Pages repository.

## Publish to GitHub Pages later

The prepared [documentation workflow](../../.github/workflows/docs.yml) builds and checks documentation changes. **Deployment runs only when manually requested.** Creating these files does not publish the site.

When ready:

1. Push the documentation source and lockfile to GitHub.
2. In **Settings → Pages**, select **GitHub Actions** as the source.
3. In **Actions → Documentation**, select **Run workflow** on the default branch.
4. Open the URL reported by the deployment job. With the current repository it is expected at `https://ruc-nlpir.github.io/FlashRSI/`; the public project page is `https://ruc-nlpir.github.io/FlashRSI/project.html`.

Pull requests and pushes build the site without deploying. Change the workflow triggers later if automatic publishing is desired.

## Edit content and navigation

Add a Markdown page and link it from `docs/.vitepress/config.mts`. Keep links relative so they also work when browsing the source on GitHub. The build rewrites links to repository code and YAML examples into GitHub links; documentation links remain within the site.

`docs/README.md` stays available as a Markdown overview and is built at `overview.html`. `docs/index.md` is the website's quickstart. All integration notes are reachable through [the reference index](../reference.md).

Before publishing, run the production build, check links and anchors, and inspect desktop and mobile layouts. Avoid putting credentials, private run logs, or experimental output into public documentation.
