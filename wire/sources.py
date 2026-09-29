"""Fetchers. Every item is normalized to:
{kind: news|reddit|study, title, url, source, published (aware datetime),
 snippet, ups, comments, extra{}}"""
from __future__ import annotations
import datetime as dt, html, os, re, time, urllib.parse
import xml.etree.ElementTree as ET
import feedparser, requests

UA = "TheWire/1.0 (personal news aggregator)"
UTC = dt.timezone.utc

def _now(): return dt.datetime.now(UTC)

# ---------- Google News (free RSS, supports when:Nd) ----------
def google_news(query: str, hours: int) -> list[dict]:
    days = max(1, round(hours / 24))
    q = f"{query} when:{days}d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    feed = feedparser.parse(requests.get(url, headers={"User-Agent": UA}, timeout=20).content)
    out = []
    for e in feed.entries:
        src = getattr(getattr(e, "source", None), "title", None) or ""
        title = e.title
        if src and title.endswith(" - " + src):
            title = title[: -len(" - " + src)]
        pub = dt.datetime(*e.published_parsed[:6], tzinfo=UTC) if getattr(e, "published_parsed", None) else _now()
        out.append({"kind": "news", "title": html.unescape(title), "url": e.link, "source": src or "Google News",
                    "published": pub, "snippet": re.sub("<[^>]+>", " ", html.unescape(getattr(e, "summary", "")))[:500],
                    "ups": 0, "comments": 0, "extra": {"query": query}})
    return out

# ---------- Reddit (official API, app-only OAuth) ----------
class Reddit:
    def __init__(self):
        cid, sec = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
        self.ok = bool(cid and sec)
        self.token = None
        if self.ok:
            r = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec),
                              data={"grant_type": "client_credentials"}, headers={"User-Agent": UA}, timeout=20)
            r.raise_for_status(); self.token = r.json()["access_token"]

    def _get(self, path, **params):
        r = requests.get("https://oauth.reddit.com" + path, params=params,
                         headers={"User-Agent": UA, "Authorization": f"bearer {self.token}"}, timeout=20)
        r.raise_for_status(); time.sleep(0.7)  # stay well under rate limits
        return r.json()

    @staticmethod
    def _post(d) -> dict:
        return {"kind": "reddit", "title": html.unescape(d["title"]),
                "url": "https://www.reddit.com" + d["permalink"], "source": "r/" + d["subreddit"],
                "published": dt.datetime.fromtimestamp(d["created_utc"], UTC),
                "snippet": (d.get("selftext") or "")[:800], "ups": d.get("score", 0),
                "comments": d.get("num_comments", 0),
                "extra": {"id": d["id"], "sub": d["subreddit"], "link": d.get("url_overridden_by_dest", "")}}

    def top(self, sub, hours):
        if not self.ok: return []
        cutoff = _now() - dt.timedelta(hours=hours)
        data = self._get(f"/r/{sub}/top", t="week", limit=100)
        return [p for p in (self._post(c["data"]) for c in data["data"]["children"]) if p["published"] >= cutoff]

    def search(self, q, hours):
        if not self.ok: return []
        cutoff = _now() - dt.timedelta(hours=hours)
        data = self._get("/search", q=q, sort="top", t="week", limit=50, type="link")
        return [p for p in (self._post(c["data"]) for c in data["data"]["children"]) if p["published"] >= cutoff]

    def by_ids(self, ids):
        if not self.ok or not ids: return []
        data = self._get("/api/info", id=",".join("t3_" + i for i in ids))
        return [self._post(c["data"]) for c in data["data"]["children"]]

    def top_comments(self, post_id, n=6):
        if not self.ok: return []
        data = self._get(f"/comments/{post_id}", limit=n, sort="top", depth=1)
        return [c["data"].get("body", "")[:400] for c in data[1]["data"]["children"] if c["kind"] == "t1"][:n]

# ---------- Google "site:reddit.com" via SerpAPI (your method; optional, paid) ----------
def serp_reddit_ids(term: str, hours: int) -> list[str]:
    key = os.getenv("SERPAPI_KEY")
    if not key: return []
    r = requests.get("https://serpapi.com/search.json", timeout=30, params={
        "engine": "google", "q": f'site:reddit.com "{term}"', "tbs": f"qdr:d{max(1, round(hours/24))}",
        "num": 30, "api_key": key})
    r.raise_for_status()
    ids = []
    for res in r.json().get("organic_results", []):
        m = re.search(r"/comments/([a-z0-9]+)/", res.get("link", ""))
        if m: ids.append(m.group(1))
    return ids  # engagement is then read from Reddit's API — search snippets don't carry it

# ---------- PubMed (free E-utilities): papers with experimental results ----------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
def pubmed(query: str, hours: int) -> list[dict]:
    if not query: return []
    days = max(1, round(hours / 24))
    term = (f"({query}) AND hasabstract AND (journal article[pt] OR preprint[pt]) "
            "NOT (review[pt] OR systematic review[pt] OR editorial[pt] OR comment[pt] OR letter[pt])")
    base = {"db": "pubmed", "api_key": os.getenv("NCBI_API_KEY", "")}
    ids = requests.get(EUTILS + "esearch.fcgi", timeout=30, params={**base, "term": term, "datetype": "edat",
                        "reldate": days, "retmax": 80, "retmode": "json"}).json()["esearchresult"]["idlist"]
    if not ids: return []
    root = ET.fromstring(requests.get(EUTILS + "efetch.fcgi", timeout=60,
                         params={**base, "id": ",".join(ids), "retmode": "xml"}).content)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        abstract = " ".join("".join(t.itertext()) for t in art.findall(".//AbstractText"))
        journal = art.findtext(".//Journal/Title") or "PubMed"
        types = [t.text for t in art.findall(".//PublicationType")]
        ez = art.find(".//PubMedPubDate[@PubStatus='entrez']")
        pub = (dt.datetime(int(ez.findtext("Year")), int(ez.findtext("Month")), int(ez.findtext("Day")), tzinfo=UTC)
               if ez is not None else _now())
        out.append({"kind": "study", "title": title, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "source": journal, "published": pub, "snippet": abstract[:3000], "ups": 0, "comments": 0,
                    "extra": {"pmid": pmid, "types": types}})
    return out

def medrxiv(keywords: list[str], hours: int) -> list[dict]:
    if not keywords: return []
    end = _now().date(); start = end - dt.timedelta(days=max(1, round(hours / 24)))
    out, cursor = [], 0
    while True:
        j = requests.get(f"https://api.biorxiv.org/details/medrxiv/{start}/{end}/{cursor}", timeout=30).json()
        for p in j.get("collection", []):
            text = (p["title"] + " " + p.get("abstract", "")).lower()
            if any(k.lower() in text for k in keywords):
                out.append({"kind": "study", "title": p["title"], "url": f"https://www.medrxiv.org/content/{p['doi']}",
                            "source": "medRxiv (preprint, not peer reviewed)",
                            "published": dt.datetime.fromisoformat(p["date"]).replace(tzinfo=UTC),
                            "snippet": p.get("abstract", "")[:3000], "ups": 0, "comments": 0,
                            "extra": {"doi": p["doi"], "types": ["Preprint"]}})
        msgs = j.get("messages", [{}])[0]
        total = int(msgs.get("total", 0)); cursor += 100
        if cursor >= total: break
    return out


# ---------- Hacker News "Show HN" (free Algolia API; points + comments) ----------
def hn_show(keywords: list[str], hours: int, min_points: int = 20) -> list[dict]:
    since = int((_now() - dt.timedelta(hours=hours)).timestamp())
    out, seen = [], set()
    for kw in keywords:
        j = requests.get("https://hn.algolia.com/api/v1/search_by_date", timeout=30, params={
            "query": kw, "tags": "show_hn", "hitsPerPage": 100,
            "numericFilters": f"created_at_i>{since},points>={min_points}"}).json()
        for h in j.get("hits", []):
            if h["objectID"] in seen: continue
            seen.add(h["objectID"])
            out.append({"kind": "hn", "title": h.get("title", ""), "source": "Hacker News",
                        "url": f"https://news.ycombinator.com/item?id={h['objectID']}",
                        "published": dt.datetime.fromtimestamp(h["created_at_i"], UTC),
                        "snippet": re.sub("<[^>]+>", " ", html.unescape(h.get("story_text") or ""))[:1500],
                        "ups": h.get("points", 0), "comments": h.get("num_comments", 0),
                        "extra": {"project_url": h.get("url", ""), "author": h.get("author", "")}})
    return out

# ---------- GitHub: brand-new repos gaining stars fast, owned by individuals/small orgs ----------
def github_new_repos(topics: list[str], hours: int, min_stars: int = 50) -> list[dict]:
    if not topics: return []
    since = (_now() - dt.timedelta(days=max(3, round(hours / 24)))).date()
    hdrs = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if os.getenv("GITHUB_TOKEN"): hdrs["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"
    out = []
    for t in topics:
        j = requests.get("https://api.github.com/search/repositories", headers=hdrs, timeout=30, params={
            "q": f"topic:{t} created:>={since} stars:>={min_stars}", "sort": "stars", "per_page": 30}).json()
        for r in j.get("items", []):
            out.append({"kind": "repo", "title": f"{r['full_name']}: {r.get('description') or ''}",
                        "url": r["html_url"], "source": "GitHub",
                        "published": dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")),
                        "snippet": (r.get("description") or "")[:500], "ups": r["stargazers_count"],
                        "comments": r.get("forks_count", 0),
                        "extra": {"owner_type": r["owner"]["type"], "homepage": r.get("homepage") or ""}})
        time.sleep(2)
    return out


# ---------- Any RSS/Atom feed (e.g. ScienceDaily health, university newsrooms) ----------
def rss(url: str, hours: int, label: str = "") -> list[dict]:
    feed = feedparser.parse(requests.get(url, headers={"User-Agent": UA}, timeout=20).content)
    cutoff = _now() - dt.timedelta(hours=hours); out = []
    for e in feed.entries:
        tp = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        pub = dt.datetime(*tp[:6], tzinfo=UTC) if tp else _now()
        if pub < cutoff: continue
        out.append({"kind": "news", "title": html.unescape(e.title), "url": e.link,
                    "source": label or feed.feed.get("title", "RSS"), "published": pub,
                    "snippet": re.sub("<[^>]+>", " ", html.unescape(getattr(e, "summary", "")))[:800],
                    "ups": 0, "comments": 0, "extra": {"feed": url}})
    return out
