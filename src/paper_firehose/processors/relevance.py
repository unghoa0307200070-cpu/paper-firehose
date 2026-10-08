"""Configurable evidence gates for process-analysis recommendations.

The result describes keyword evidence, not a model confidence or a claim
that an article is suitable for a particular instrument.
"""
import html
import re


def plain_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()


def evidence_text(value):
    # Several journal feeds provide citation paragraphs rather than abstracts.
    # Journal names and author metadata must not satisfy content requirements.
    def keep_paragraph(match):
        text = plain_text(match.group(0))
        return " " if re.match(r"(?:Publication date|Source|Author\(s\))\s*:", text, re.I) else match.group(0)
    value = re.sub(r"<p\b[^>]*>.*?</p>", keep_paragraph, str(value or ""), flags=re.I | re.S)
    return plain_text(value)


class RelevancePolicy:
    def __init__(self, config):
        self.config = config or {}
        self.excluded = re.compile(self.config.get("exclude_title_pattern") or r"(?!)", re.I)
        self.routes = [
            (route, [re.compile(pattern, re.I) for pattern in route["all_patterns"]])
            for route in self.config.get("routes", [])
        ]
        self.modalities = [
            (label, re.compile(pattern, re.I))
            for label, pattern in self.config.get("modalities", {}).items()
        ]

    def evaluate(self, entry):
        title = plain_text(entry.get("title"))
        if self.excluded.search(title):
            return None
        text = " ".join(evidence_text(entry.get(field)) for field in ("title", "summary", "abstract"))
        modalities = [label for label, regex in self.modalities if regex.search(text)]
        for route, patterns in self.routes:
            evidence = [pattern.search(text) for pattern in patterns]
            if all(evidence):
                return {
                    "label": route["label"],
                    "priority": int(route.get("priority", 0)),
                    "boost": float(route.get("boost", 0)),
                    "evidence": list(dict.fromkeys(match.group(0) for match in evidence)),
                    "modalities": modalities,
                }
        # Existing topics without a relevance policy retain their old behavior.
        if not self.routes:
            return {"label": "候选文献", "priority": 0, "boost": 0, "evidence": [], "modalities": modalities}
        return None
