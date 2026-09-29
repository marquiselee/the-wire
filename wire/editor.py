"""The editor: one Claude call per story cluster. Writes the headline/summary, flags contradictions,
rates importance, and rejects off-topic, low-substance, or result-free items."""
import json, os, re

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

class Editor:
    def __init__(self, model):
        self.model = model
        self.client = None
        if os.getenv("ANTHROPIC_API_KEY"):
            import anthropic
            self.client = anthropic.Anthropic()

    def edit(self, group, tab):
        if not self.client:
            return self.fallback(group)
        msg = self.client.messages.create(
            model=self.model, max_tokens=900, system=SYSTEM,
            messages=[{"role": "user", "content": f"TAB: {tab['tab']} — {tab['topic_note']}\n" + (f"TAB RULES: {tab['editor_rules']}\n" if tab.get('editor_rules') else "") + f"\nREPORTS:\n{_fmt(group)}"}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def fallback(group):  # dry-run mode: no API key
        it = group[0]
        return {"keep": True, "same_event": True, "headline": it["title"].upper()[:110],
                "summary": re.sub(r"\s+", " ", it["snippet"])[:300] or it["title"],
                "takeaways": ["(dry run — no editor model)"] * 3, "conflict": None,
                "importance": 3, "study": None, "community": it["kind"] == "reddit"}
