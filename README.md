# The Wire — automated build

Refreshes on demand when you tap the Refresh button on the site or manually run the workflow. The site includes a Refresh button (⟳) that links to the workflow run page.

## What it pulls (per tab, last 96 hours)
| Source | How | Cost |
|---|---|---|
| RSS feeds | Any feed listed per tab (e.g. ScienceDaily Health, Fitness, Skin Care) | Free |
| Google News | RSS search with `when:3d` for each query in `config.yaml` | Free |
| Reddit | Official API: top posts in listed subreddits + keyword search, with upvotes and comment counts | Free (app-only OAuth) |
| Google `site:reddit.com "term"` | SerpAPI with a past-3-days filter; engagement then read from Reddit's API | Optional, ~$75/mo |
| PubMed | Papers entered in the window, with abstracts, excluding reviews/editorials/letters | Free |
| medRxiv | Preprints matching keywords (labeled "not peer reviewed") | Free |
| Hacker News "Show HN" | Algolia API, AI-related launches with points and comment counts | Free |
| GitHub | New repos (last few days) on AI topics, sorted by stars, owner type passed to the editor | Free (Actions token) |

## What the editor (Claude) does per story
Merges up to 3 reports, writes the headline/summary/3 takeaways in its own words, flags contradictions
between sources, rates importance 1–5, and drops anything off-topic, promotional, price-chatter, or low-substance.
Studies are kept only if they report experimental results; their takeaways list design, n, result and caveat.

## AI Projects tab
The editor asks of every project: is it useful, is it new, or does it do something familiar in a new way — and at
minimum, is it interesting? Only individuals or teams of about five or fewer qualify. Chatbot re-skins, generic
"AI for X" SaaS and prompt packs are rejected. No single category (e.g. agent memory, coding tools) can take more
than 3 slots, so the tab stays varied. Each story says why it's there and which test it passed.

## Ranking rules (see `config.yaml`)
- Nothing older than 96 h (4 days). Items 24–96 h old stay only if buzz ≥ 50 or importance ≥ 4 (studies exempt).
- Buzz = outlets covering it (up to 40) + Reddit engagement (log of upvotes + 2×comments, up to 40) + 20 if it started on Reddit.
- Rank = importance×15 + buzz×0.5 + freshness×30. Top story leads; next three go above the masthead. Max 40 per tab.
- If fewer than 20 stories clear the bar, the page says so instead of padding.

## Setup (about 15 minutes)
1. New GitHub repo → upload these files → Settings → Pages → Source: **GitHub Actions**.
2. Settings → Secrets → Actions: add `ANTHROPIC_API_KEY`; for Reddit create a "script" app at reddit.com/prefs/apps and add
   `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. Optional: `SERPAPI_KEY`, `NCBI_API_KEY`.
3. Actions → "Build The Wire" → Run workflow. The page appears at `https://<you>.github.io/<repo>/`.

Edit `config.yaml` to add tabs, queries, subreddits or tune thresholds. `python tests/test_offline.py` runs a no-network check.
Note: Google News links go through news.google.com redirects to the publisher.

## Changing the site from your phone (@claude)
1. Install the Claude GitHub app on this repo (github.com/apps/claude) — you must be the repo admin.
2. The workflow `.github/workflows/claude.yml` is already included and uses the same `ANTHROPIC_API_KEY` secret.
3. Open an issue like: "@claude add a Sports tab covering the Phillies, Eagles, Sixers and Flyers".
   Claude opens a pull request; review and merge it; the next scheduled build (or Run workflow) publishes it.
Only your own @claude mentions trigger it. `CLAUDE.md` tells Claude how the repo is organized.

## Cost controls
- **Reused summaries.** Each build reads the previous build's editor decisions back out of the published page
  (a hidden `editor-cache` block) and only asks Claude about stories it has not seen before. A story that gains a new
  report, or a change to the editor rules or model, is re-summarized. Rejected stories are remembered too.
  The first build after setup (or after a change to the rules/model) pays for everything; later builds are mostly free.
- **Model.** `model` in `config.yaml` is Claude Haiku 4.5 (cheap). Set it to `claude-sonnet-5-5` for sharper judgement
  on conflicts, study details and the AI Projects rules, at roughly 3x the cost.
- The build log ends with a line like `Editor: 41 new summaries, 187 reused from the last build`.
