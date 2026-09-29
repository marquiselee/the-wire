# Notes for Claude working in this repo
- The page is built by `run.py` from `config.yaml` (tabs, sources, thresholds) and `template/page.html`.
- Most requests ("add a tab", "change sources", "tighten the editor") are edits to `config.yaml`.
- Layout/visual changes go in `template/page.html`; keep the Drudge-style look and the `/*__DATA__*/[]` placeholder.
- Run `python tests/test_offline.py` before opening a PR.
- Never commit API keys; they live in repository secrets.
