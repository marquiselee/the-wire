"""Buzz (0-100) and editorial rank.
buzz = coverage (distinct outlets, up to 40) + community engagement (Reddit, up to 40) + social origin (+20)"""
import datetime as dt, math

def outlets(group):  # distinct publishers, not counting Reddit/studies
    return len({it["source"].lower() for it in group if it["kind"] == "news"})

COMMUNITY = ("reddit", "hn", "repo")
LABEL = {"reddit": ("upvotes", "comments"), "hn": ("points", "comments"), "repo": ("stars", "forks")}

def reddit_points(group):  # any community source: Reddit upvotes, HN points, GitHub stars
    best = 0.0
    for it in group:
        if it["kind"] in COMMUNITY:
            best = max(best, 8 * math.log10(1 + it["ups"] + 2 * it["comments"]))
    return min(40.0, best)

def buzz(group) -> dict:
    cov = min(40, 5 * outlets(group))
    red = reddit_points(group)
    origin = 20 if any(it["kind"] in COMMUNITY for it in group) else 0
    score = int(round(min(100, cov + red + origin)))
    top = max((it for it in group if it["kind"] in COMMUNITY), key=lambda x: x["ups"], default=None)
    parts = [f"{outlets(group)} outlets on Google News"] if outlets(group) else []
    if top:
        a, b = LABEL[top["kind"]]
        parts.append(f"{top['source']}: {top['ups']:,} {a}, {top['comments']:,} {b}")
    return {"score": score, "note": "; ".join(parts) or "Single source", "outlets": outlets(group)}

def age_hours(group, now):
    newest = max(it["published"] for it in group)
    return (now - newest).total_seconds() / 3600

def keep(group, b, importance, cfg, now) -> bool:
    age = age_hours(group, now)
    if age > cfg["window_hours"]: return False
    if age <= cfg["keep_after_hours"]: return True
    if any(it["kind"] == "study" for it in group): return True  # studies rarely get buzz; judge them on results
    return b["score"] >= cfg["keep_min_buzz"] or importance >= cfg["keep_min_importance"]

def prelim(group, now, window=96):  # before the editor model has weighed in
    return buzz(group)["score"] * 0.6 + max(0, window - age_hours(group, now)) * 0.5 + 5 * len(group)

def rank(importance, b, age, window=96):
    fresh = max(0.0, 1 - age / window)
    return importance * 15 + b["score"] * 0.5 + fresh * 30
