"""Build The Wire. Usage: python run.py [--out site/index.html]
Env: ANTHROPIC_API_KEY (editor), REDDIT_CLIENT_ID/SECRET (community + engagement),
     SERPAPI_KEY (optional Google site:reddit.com search), NCBI_API_KEY (optional, faster PubMed)."""
import argparse, datetime as dt, pathlib, sys, traceback, yaml
from wire import sources, cluster, score, editor, render

def gather(tab, cfg, reddit):
    H = cfg["window_hours"]; items = []
    def safe(fn, *a):
        try: items.extend(fn(*a))
        except Exception: traceback.print_exc(file=sys.stderr)
    for q in tab.get("google_news", []): safe(sources.google_news, q, H)
    for f in tab.get("rss", []): safe(sources.rss, f["url"], H, f.get("label", ""))
    for s in tab.get("reddit_subs", []): safe(reddit.top, s, H)
    for q in tab.get("reddit_search", []): safe(reddit.search, q, H)
    for q in tab.get("reddit_search", []) + [tab["tab"].lower()]:
        try: items.extend(reddit.by_ids(sources.serp_reddit_ids(q, H)))
        except Exception: traceback.print_exc(file=sys.stderr)
    if tab.get("hn_show"): safe(sources.hn_show, tab["hn_show"], H, cfg.get("hn_min_points", 20))
    if tab.get("github_topics"): safe(sources.github_new_repos, tab["github_topics"], H, cfg.get("github_min_stars", 50))
    safe(sources.pubmed, tab.get("pubmed", ""), H)
    safe(sources.medrxiv, tab.get("medrxiv_keywords", []), H)
    now = dt.datetime.now(dt.timezone.utc)
    items = [it for it in cluster.dedupe(items)
             if (now - it["published"]).total_seconds() <= H * 3600
             and (it["kind"] != "reddit" or (it["ups"] >= cfg["reddit_min_score"] and it["comments"] >= cfg["reddit_min_comments"]))]
    for it in items:
        if it["kind"] == "reddit":
            try: it["extra"]["comments"] = reddit.top_comments(it["extra"]["id"])
            except Exception: pass
    return items

def build_tab(tab, cfg, reddit, ed):
    now = dt.datetime.now(dt.timezone.utc)
    groups = cluster.cluster(gather(tab, cfg, reddit))
    groups.sort(key=lambda g: score.prelim(g, now, cfg["window_hours"]), reverse=True)
    stories = []
    for g in groups[: cfg["llm_candidates_per_tab"]]:
        e = ed.edit(g, tab)
        if not e or not e.get("keep"): continue
        pj = e.get("project")
        if tab.get("editor_rules") and tab.get("require_project_check"):
            # the editor's question: useful, new, or done in a new way — and at minimum interesting; small teams only
            if not pj or not pj.get("small_team") or not pj.get("interesting"): continue
        if not e.get("same_event", True): g = g[:1]
        b = score.buzz(g); imp = int(e.get("importance", 3))
        if not score.keep(g, b, imp, cfg, now): continue
        age = score.age_hours(g, now)
        s = {"h": e["headline"], "links": render.pick_links(g, cfg["max_links_per_story"]),
             "sum": e["summary"], "take": e.get("takeaways", [])[:3],
             "buzz": {"score": b["score"], "note": b["note"]},
             "_rank": score.rank(imp, b, age, cfg["window_hours"])}
        if e.get("conflict"): s["conflict"] = e["conflict"]
        if pj and tab.get("require_project_check"):
            tags = [k.replace("_", " ") for k in ("useful", "new", "new_approach") if pj.get(k)] or ["interesting"]
            s["take"] = [f"Why it's here: {pj.get('why','')}", "Editor's check: " + ", ".join(tags)] + s["take"][:1]
            s["_cat"] = (pj.get("category") or "other").lower()
        if e.get("community"): s["talk"] = True
        st = e.get("study")
        if st:
            s["study"] = True
            s["take"] = [f"Design: {st.get('design','')}; n = {st.get('n','')}; {st.get('population','')}",
                         f"Result: {st.get('result','')}", f"Caveat: {st.get('caveat','')}"]
        stories.append(s)
    stories.sort(key=lambda s: s["_rank"], reverse=True)
    cap = tab.get("max_per_category")
    if cap:  # force variety: no single kind of project can crowd out the rest
        counts, varied = {}, []
        for s in stories:
            c = s.get("_cat", "other"); counts[c] = counts.get(c, 0) + 1
            if counts[c] <= cap: varied.append(s)
        stories = varied
    stories = stories[: cfg["max_stories"]]
    for i, s in enumerate(stories):
        s.pop("_rank"); s.pop("_cat", None)
        if i == 0: s["slot"] = "lead"
        elif i <= 3: s["slot"] = "top"
        if s["buzz"]["score"] >= 80: s["hot"] = True
    feed = {k: tab[k] for k in ("key", "tab", "masthead", "blurb")}
    feed["stories"] = stories
    feed["short"] = len(stories) < cfg["min_stories"]
    return feed

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="site/index.html")
    ap.add_argument("--config", default="config.yaml"); a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    reddit = sources.Reddit(); ed = editor.Editor(cfg["model"])
    feeds = [build_tab(t, cfg, reddit, ed) for t in cfg["tabs"]]
    tpl = (pathlib.Path(__file__).parent / "template/page.html").read_text()
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render.page(tpl, feeds, dt.datetime.now(dt.timezone.utc), round(cfg["window_hours"] / 24)))
    for f in feeds: print(f"{f['tab']}: {len(f['stories'])} stories")

if __name__ == "__main__":
    main()
