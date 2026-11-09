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

## Experiment explorer

The [SkillOpt × SearchQA explorer](../experiments/skillopt-searchqa.md) uses a static display dataset under `docs/public/experiment-data/`. It includes selected historical candidate decisions, skill comparisons, development evaluations, and progress logs. Sealed-test results and complete model transcripts are not included.

To regenerate the display dataset from the curated historical experiment directory:

```bash
python scripts/export_skillopt_explorer.py \
  --source /path/to/skillopt-searchqa-deepseek-20260920-seed42 \
  --output docs/public/experiment-data/skillopt-searchqa.json
```

The exporter selects display fields rather than copying model configs or the original experiment directory. Review the exported text before publishing. The page is built and hosted with the existing documentation site; it needs no backend or model API.

### Adding another experiment

The viewer takes a `data-path` and reads its titles, models, splits, update schedule, and records from that JSON file. It is shared across experiment pages.

1. Export a display JSON into `docs/public/experiment-data/`. The current exporter handles the curated SkillOpt/SearchQA archive; other log formats need their own mapping to the display schema.
2. Copy `docs/experiments/skillopt-searchqa.md`, update its title and description, and point `data-path` at the new JSON.
3. Add the page to `docs/experiments/index.md`, then build and check the site before deploying.

The display schema uses `schemaVersion: 1`, experiment metadata (`algorithm`, `benchmark`, `date`, `dateLabel`, `seed`, `dataset`, `description`, and `metric`), and an `agents` mapping. Each agent includes its label, models, splits, initial dev score, accepted count, candidate decisions, development evaluations, and progress logs. Decisions carry scores, acceptance, rationale, proposed edits, and before/after file comparisons. The TypeScript types in `docs/.vitepress/theme/ExperimentExplorer.vue` define these fields.

Use `null` for an unscored candidate. Preserve the recorded acceptance decisions and keep test scores and answers out of this display dataset, including log summaries. Missing conversations must remain missing rather than being reconstructed as model transcripts. Updating an existing experiment only requires regenerating its display JSON and rebuilding the site.

### Selection-aware SearchQA views

The [experiment index](../experiments/index.md) also includes eleven method-specific views using `schemaVersion: 2`. These pages use `SelectionExplorer.vue` for harness selection, resource comparison, and the event ledger. The components under `docs/.vitepress/theme/selection/` each implement a method's actual selection process, rather than assigning every event a generic accepted/rejected dev update.

Regenerate these display datasets from reduced historical run records:

```bash
python scripts/export_searchqa_explorers.py \
  --records /path/to/reduced-searchqa-records \
  --output docs/public/experiment-data/searchqa
```

The input contains `records/<algorithm>-<harness>.json`, with recorded non-test algorithm events, evaluation summaries, source model configuration, and deduplicated resource states/text. DarwinX additionally uses `records-full/` to preserve its original branch search alongside the later fixed-archive reselection. The exporter selects public model names without publishing connection settings, omits test evaluation stages, and keeps the recorded selected artifact. Resource text is a separate file, loaded only when a visitor opens a comparison.

Each method's **View diff** action opens the shared file inspector within its selection view and preserves the current selection. The inspector supports added/removed lines with folded unchanged context, complete before/after text, side-by-side comparisons, and recorded executable flags. Its default comparison is the recorded parent when available, otherwise the initial version; visitors can select a different base. The line diff normalizes CRLF, while the complete text retains the archived content. Large unrelated files use a bounded full-replacement display.

Adding more runs of an existing method means mapping their records to that method's display fields and adding a page entry. A new selection policy needs its own view: train optimization is not dev selection, archive admission is not final promotion, and a successful execution gate is not a correct answer. Do not silently replay a new selection rule over historical scores. Mark missing evidence as missing.
