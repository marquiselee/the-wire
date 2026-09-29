import datetime as dt, json
from zoneinfo import ZoneInfo
ET_TZ = ZoneInfo("America/New_York")

def fmt_link(it):
    t = it["published"].astimezone(ET_TZ)
    d = {"src": it["source"], "url": it["url"], "date": t.strftime("%b ") + str(t.day) + t.strftime(", %Y")}
    if it["kind"] != "study" and (t.hour or t.minute):
        d["time"] = (str(t.hour % 12 or 12) + t.strftime(":%M") + ("am" if t.hour < 12 else "pm"))
    return d

def pick_links(group, n):
    # prefer distinct sources, newest first, keep a Reddit thread if there is one
    seen, out = set(), []
    ordered = sorted(group, key=lambda x: (x["kind"] != "reddit", -x["published"].timestamp()))
    for it in ordered:
        if it["source"] in seen: continue
        seen.add(it["source"]); out.append(it)
        if len(out) == n: break
    return [fmt_link(it) for it in out]

def page(template: str, feeds: list[dict], updated: dt.datetime, days: int = 4) -> str:
    stamp = updated.astimezone(ET_TZ)
    upd = stamp.strftime("%a %b ") + str(stamp.day) + ", " + str(stamp.hour % 12 or 12) + stamp.strftime(":%M") + ("am" if stamp.hour < 12 else "pm") + " ET"
    for f in feeds: f["stamp"] = f"{f['blurb']} \u00b7 Last {days} days \u00b7 Updated {upd}"
    data = json.dumps(feeds, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("/*__DATA__*/[]", data)
