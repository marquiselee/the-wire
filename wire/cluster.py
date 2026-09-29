"""Group reports about the same event. Cheap token overlap first; the editor model can still split."""
import re
STOP = set("""a an the of to in on for and or but with at by from as is are was were be been it its this that
these those after before over under into about amid new says say said will would could may might how why what
who when where vs vs. v up down out more most than just his her their our your we you they he she i""".split())

def tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9$%.]+", title.lower())
    return {w.strip(".") for w in words if w not in STOP and len(w) > 2}

def similar(a: set, b: set) -> bool:
    if not a or not b: return False
    inter = len(a & b)
    return inter >= 4 or inter / len(a | b) >= 0.34

def cluster(items: list[dict]) -> list[list[dict]]:
    parent = list(range(len(items)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    toks = [tokens(it["title"]) for it in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            # studies and Reddit threads are clustered only with their own kind
            if items[i]["kind"] != items[j]["kind"] and "study" in (items[i]["kind"], items[j]["kind"]):
                continue
            if similar(toks[i], toks[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    return list(groups.values())

def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = (it["url"].split("?")[0], it["title"].lower()[:80])
        if key in seen: continue
        seen.add(key); out.append(it)
    return out
