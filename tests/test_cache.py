"""Cache test: a second build must reuse the first build's editor decisions and make zero API calls."""
import datetime as dt, json, pathlib, sys, tempfile, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))
from wire import editor

now = dt.datetime.now(dt.timezone.utc)
def grp(url): return [{"kind": "news", "title": "T " + url, "url": url, "source": "S", "published": now,
                       "snippet": "text", "ups": 0, "comments": 0, "extra": {}}]
tab = {"key": "crypto", "tab": "Crypto", "topic_note": "x"}

class Msg:  # minimal stand-in for an Anthropic response
    def __init__(self, body): self.content = [types.SimpleNamespace(type="text", text=body)]
class FakeClient:
    def __init__(self): self.n = 0; self.messages = self
    def create(self, **kw):
        self.n += 1
        keep = "reject" not in kw["messages"][0]["content"]
        return Msg(json.dumps({"keep": keep, "same_event": True, "headline": "H", "summary": "s",
                               "takeaways": ["a", "b", "c"], "importance": 3}))

ed = editor.Editor("m"); ed.client = FakeClient()
for u in ("https://a", "https://b", "https://reject"): ed.edit(grp(u), tab)
assert ed.calls == 3 and ed.hits == 0
page = editor.embed_cache("<html><body>hi</body></html>", ed.export())
assert 'id="editor-cache"' in page and "</script></body>" in page
cache = editor.parse_cache(page)
assert len(cache) == 3, cache
assert any(v["e"] == {"keep": False} for v in cache.values()), "rejections should be remembered in tiny form"

ed2 = editor.Editor("m", cache); ed2.client = FakeClient()
for u in ("https://a", "https://b", "https://reject"): ed2.edit(grp(u), tab)
assert ed2.client.n == 0 and ed2.hits == 3, (ed2.client.n, ed2.hits)          # nothing re-summarized
g = grp("https://a") + grp("https://a2"); ed2.edit(g, tab)
assert ed2.client.n == 1, "a story that gained a new report must be re-summarized"
ed3 = editor.Editor("other-model", cache); ed3.client = FakeClient(); ed3.edit(grp("https://a"), tab)
assert ed3.client.n == 1, "changing the model must refresh"

old = {"k": {"e": {"keep": False}, "seen": "2000-01-01"}}
assert editor.Editor("m", old).export() == {}, "stale entries must be pruned"
f = pathlib.Path(tempfile.mkdtemp()) / "prev.html"; f.write_text(page)
assert len(editor.load_cache(str(f))) == 3
assert editor.load_cache("https://127.0.0.1:9/nope") == {}, "unreachable cache must degrade to empty"
print("cache OK")
