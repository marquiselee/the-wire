"""Offline test: fixture items -> cluster -> score -> render (no network, no API key)."""
import datetime as dt, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import types; sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))
import yaml
from wire import cluster, score, render, editor
import run

now = dt.datetime.now(dt.timezone.utc)
def item(kind, title, src, hrs, ups=0, com=0):
    return {"kind": kind, "title": title, "url": f"https://example.com/{abs(hash(title))}", "source": src,
            "published": now - dt.timedelta(hours=hrs), "snippet": title, "ups": ups, "comments": com, "extra": {}}

items = [
  item("news", "Bitget reopens withdrawals after $388 million hack", "The Block", 5),
  item("news", "Bitget resumes withdrawals following $387.5 million hack", "FXStreet", 6),
  item("news", "Bitget withdrawals resume after hack, CEO says attacker tested controls", "Decrypt", 7),
  item("reddit", "Bitget withdrawals resume after $388 million hack — anyone got funds out?", "r/CryptoCurrency", 4, 2400, 610),
  item("news", "Chainlink launches CCIP 2.0 with custom verifiers", "CoinDesk", 20),
  item("news", "Old story", "Somewhere", 80),
  item("study", "Retatrutide versus placebo in adults with obesity: randomized trial", "NEJM", 30),
]
items = [i for i in items if (now - i["published"]).total_seconds() <= 72*3600]
groups = cluster.cluster(items)
assert any(len(g) == 4 for g in groups), [len(g) for g in groups]
big = max(groups, key=len)
b = score.buzz(big)
assert b["score"] >= 60, b
print("bitget buzz", b)

cfg = yaml.safe_load(open(pathlib.Path(__file__).parents[1] / "config.yaml"))
class FakeReddit:
    ok=False
    def top(self,*a): return []
    def search(self,*a): return []
    def by_ids(self,*a): return []
    def top_comments(self,*a): return []
run.gather = lambda tab, cfg, reddit: items
feed = run.build_tab(cfg["tabs"][2], cfg, FakeReddit(), editor.Editor(cfg["model"]))
assert feed["stories"][0]["slot"] == "lead"
html = render.page((pathlib.Path(__file__).parents[1] / "template/page.html").read_text(), [feed], now)
data = re.search(r"const FEEDS = (\[.*?\]);\n", html, re.S).group(1)
parsed = json.loads(data.replace("<\\/", "</"))
print(len(parsed[0]["stories"]), "stories;", parsed[0]["stories"][0]["h"][:60], parsed[0]["stories"][0]["buzz"])
pathlib.Path("/tmp/wire_test.html").write_text(html)
print("OK")

# --- AI Projects gate + diversity cap ---
class FakeEditor:
    def edit(self, g, tab):
        t = g[0]["title"]
        return {"keep": True, "same_event": True, "headline": t.upper(), "summary": t, "takeaways": ["a", "b", "c"],
                "conflict": None, "importance": 3, "study": None, "community": False,
                "project": {"small_team": "BigCo" not in t, "interesting": "boring" not in t, "useful": True,
                            "new": False, "new_approach": True, "why": "because", "category": "memory" if "memory" in t else t.split()[0]}}
proj = [item("hn", f"memory tool number {i} for agents", "Hacker News", 3, 200 + i, 40) for i in range(5)] + [
        item("hn", "Knitting pattern generator from photos", "Hacker News", 5, 150, 30),
        item("hn", "BigCo launches enterprise agent", "Hacker News", 2, 900, 300),
        item("repo", "someone/boring-wrapper: boring chatbot skin", "GitHub", 10, 400, 10)]
run.gather = lambda tab, cfg, reddit: proj
tab = [t for t in cfg["tabs"] if t["key"] == "aiprojects"][0]
f2 = run.build_tab(tab, cfg, FakeReddit(), FakeEditor())
heads = [s["h"] for s in f2["stories"]]
assert not any("BIGCO" in h or "BORING" in h for h in heads), heads
assert sum("MEMORY" in h for h in heads) <= 3, heads
assert any("KNITTING" in h for h in heads)
print("projects gate OK:", len(heads), "stories")
