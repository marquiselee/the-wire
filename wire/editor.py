"""The editor: one Claude call per story cluster. Writes the headline/summary, flags contradictions,
rates importance, and rejects off-topic, low-substance, or result-free items."""
import datetime as dt, hashlib, json, os, re

SYSTEM = """You are the editor of a Drudge-style news page. You receive several reports that may be about the same
event. Return ONLY a JSON object, no prose, with these keys:
  keep: boolean — false if off-topic for the tab, promotional (sellers, affiliate posts, token shilling),
        price-prediction chatter, or lacking substance. For Reddit threads, keep only real discussion of a
        substantive topic. For studies, keep only papers reporting results from an experiment
        (trials, lab or animal experiments, cohort analyses) — not reviews, protocols, or opinion.
  same_event: boolean — false if the reports are about different events (then describe only the first).
  headline: ALL-CAPS headline under 110 characters, factual, no clickbait.
  summary: 2-4 plain sentences in your own words. Never copy sentences from the sources.
  takeaways: array of exactly 3 short factual bullets.
  conflict: null, or 1-3 sentences naming which sources disagree and on what (numbers, dates, attributions,
            framing that changes the meaning). Only real disagreements between the provided sources.
  importance: integer 1-5 for readers who follow this tab (5 = major development).
  study: null, or {"design": "...", "population": "...", "n": "...", "result": "...", "caveat": "..."} for studies.
  community: true if the item is primarily a community discussion (Reddit/Substack) rather than news.
  project: null, or for project tabs {"small_team": bool, "useful": bool, "new": bool, "new_approach": bool,
           "interesting": bool, "why": "one sentence on what makes it worth a look", "category": "short label"}.
Use only facts present in the reports. Follow any TAB RULES given."""

def _fmt(group):
    lines = []
    for i, it in enumerate(group[:8], 1):
        eng = f" | {it['ups']} upvotes/points/stars, {it['comments']} comments/forks" if it["kind"] in ("reddit", "hn", "repo") else ""
        if it["kind"] == "repo": eng += f" | owner type: {it['extra'].get('owner_type')}"
        types = f" | types: {', '.join(it['extra'].get('types', []))}" if it["kind"] == "study" else ""
        lines.append(f"[{i}] ({it['kind']}) {it['source']} | {it['published']:%Y-%m-%d %H:%M} UTC{eng}{types}\n"
                     f"TITLE: {it['title']}\nTEXT: {it['snippet'][:1500]}\n"
                     + ("TOP COMMENTS: " + " || ".join(it['extra'].get('comments', [])) if it['extra'].get('comments') else ""))
    return "\n\n".join(lines)

CACHE_RE = re.compile(r'<script type="application/json" id="editor-cache">(.*?)</script>', re.S)
CACHE_KEEP_DAYS = 6   # entries not seen for this long are dropped

def _today():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

def parse_cache(html: str) -> dict:
    m = CACHE_RE.search(html or "")
    if not m: return {}
    try: return json.loads(m.group(1))
    except json.JSONDecodeError: return {}

def embed_cache(html: str, cache: dict) -> str:
    blob = json.dumps(cache, separators=(",", ":")).replace("</", "<\\/")
    tag = f'<script type="application/json" id="editor-cache">{blob}</script>'
    html = CACHE_RE.sub("", html)
    return html.replace("</body>", tag + "</body>", 1)

def load_cache(src: str | None = None) -> dict:
    """Editor decisions from the previous build, read back from the live site (or a local file for tests).
    Any failure just means an empty cache: the build then pays for every story, nothing breaks."""
    try:
        src = src or os.getenv("WIRE_CACHE_FROM")
        if src and os.path.exists(src):
            return parse_cache(open(src, encoding="utf-8").read())
        repo = os.getenv("GITHUB_REPOSITORY")  # "owner/repo", set automatically on GitHub Actions
        if not src and repo:
            import requests
            owner, name = repo.split("/", 1)
            src = f"https://{owner.lower()}.github.io/{name}/?t={dt.datetime.now().timestamp():.0f}"
        if src and src.startswith("http"):
            import requests
            r = requests.get(src, timeout=30, headers={"Cache-Control": "no-cache"})
            r.raise_for_status()
            return parse_cache(r.text)
    except Exception as ex:
        print(f"note: no previous editor cache ({type(ex).__name__}); every story will be summarized fresh")
    return {}

class Editor:
    def __init__(self, model, cache=None):
        self.model = model
        self.client = None
        self.calls = 0
        self.hits = 0
        self.errors = []
        self.old_cache = cache or {}   # key -> {"e": decision, "seen": "YYYY-MM-DD"}
        self.new_cache = {}
        if os.getenv("ANTHROPIC_API_KEY"):
            import anthropic
            self.client = anthropic.Anthropic()

    def _key(self, group, tab):
        """Same reports + same rules + same model -> same key. A new report joining a story changes the key."""
        parts = [tab["key"], SYSTEM, tab.get("topic_note", ""), tab.get("editor_rules", ""),
                 str(tab.get("require_project_check", "")), self.model] + sorted(it["url"] for it in group[:8])
        return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]

    def export(self) -> dict:
        """Cache to embed in the page: this run's entries plus recent older ones."""
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=CACHE_KEEP_DAYS)).strftime("%Y-%m-%d")
        out = {k: v for k, v in self.old_cache.items() if v.get("seen", "") >= cutoff}
        out.update(self.new_cache)
        return out

    def edit(self, group, tab):
        if not self.client:
            return self.fallback(group)
        key = self._key(group, tab)
        if key in self.old_cache:
            self.hits += 1
            self.new_cache[key] = {"e": self.old_cache[key]["e"], "seen": _today()}
            return self.old_cache[key]["e"]
        self.calls += 1
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=900, system=SYSTEM,
                messages=[{"role": "user", "content": f"TAB: {tab['tab']} — {tab['topic_note']}\n" + (f"TAB RULES: {tab['editor_rules']}\n" if tab.get('editor_rules') else "") + f"\nREPORTS:\n{_fmt(group)}"}])
        except Exception as ex:  # one bad call must not kill the whole build
            self.errors.append(f"{type(ex).__name__}: {ex}")
            return None
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None
        if data is not None:  # rejected stories are remembered too, in a tiny form, so they are never re-asked
            self.new_cache[key] = {"e": data if data.get("keep") else {"keep": False}, "seen": _today()}
        return data

    @staticmethod
    def fallback(group):  # dry-run mode: no API key
        it = group[0]
        return {"keep": True, "same_event": True, "headline": it["title"].upper()[:110],
                "summary": re.sub(r"\s+", " ", it["snippet"])[:300] or it["title"],
                "takeaways": ["(dry run — no editor model)"] * 3, "conflict": None,
                "importance": 3, "study": None, "community": it["kind"] == "reddit"}
