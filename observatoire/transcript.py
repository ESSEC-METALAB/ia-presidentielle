"""YouTube auto-caption handling.

Auto-generated VTT is not clean text. Each real cue carries two lines: the
previous line repeated as rolling context, and the new words wrapped in
per-word timing tags. Between them sit 10ms "repaint" cues. Naively reading
the file gives you every sentence two or three times.

It also carries **no speaker labels** — no ``<v>`` tags, no turn markers — so a
transcript of an interview cannot tell you whether a sentence is the candidate
or the journalist. That is why ``sources.yaml`` requires ``speakers`` on every
video source and only ``single`` becomes a claim.
"""

from __future__ import annotations

import re

_CUE = re.compile(r"^(\d\d):(\d\d):(\d\d)\.(\d+)\s+-->")
_TAG = re.compile(r"<[^>]+>")

# Two tiers, because bare French policy words do not discriminate. Measured on
# a real 43-minute programme: "données" matched a discussion of corporate tax
# and "calcul" matched "c'est des calculs" about election tactics. One strong
# term is enough; weak terms need corroboration.
_STRONG = re.compile(
    r"""intelligence\s+artificielle | \bIA\b | algorithm | machine\s+learning
      | apprentissage\s+automatique | \bLLM\b | chatgpt | openai | anthropic
      | mistral | data\s*-?\s*cent | souverainet[ée]\s+num[ée]rique
      | (?:puissance|capacit[ée]s?)\s+de\s+calcul | deepfake | hypertrucage
      | reconnaissance\s+faciale | AI\s+Act""",
    re.X | re.I,
)
_WEAK = re.compile(
    r"\bnum[ée]rique|\bdonn[ée]es|automatisation|\brobot|\bcloud\b|technologi",
    re.I,
)

def parse_vtt(text: str) -> list[tuple[int, str]]:
    """``[(start_second, line)]`` — new content only, tags stripped."""
    out: list[tuple[int, str]] = []
    t: int | None = None
    for line in text.splitlines():
        m = _CUE.match(line)
        if m:
            h, mi, s, _ms = (int(g) for g in m.groups())
            t = h * 3600 + mi * 60 + s
            continue
        # Only lines carrying inline timing tags are new; the rest is repaint.
        if t is None or "<" not in line:
            continue
        cleaned = _TAG.sub("", line).strip()
        if cleaned and (not out or out[-1][1] != cleaned):
            out.append((t, cleaned))
    return out


def flatten(cues: list[tuple[int, str]]) -> str:
    return " ".join(c[1] for c in cues)


def mentions_ai(text: str) -> bool:
    """Prefilter. Video only — a 90-minute transcript is ~29K tokens, roughly
    ten times a news article, so it is worth checking before spending a call.
    Text sources skip this: saving a dollar is not worth a false negative.

    One strong term passes. Otherwise two *distinct* weak terms are required,
    so a single stray "données" in a tax debate does not drag in a 29K-token
    transcript.
    """
    if _STRONG.search(text):
        return True
    return len({m.group(0).lower() for m in _WEAK.finditer(text)}) >= 2


def locate(cues: list[tuple[int, str]], quote: str) -> int | None:
    """Second at which ``quote`` is spoken, or ``None`` if it is not present.

    One operation, two jobs: the return value is the citation timestamp, and
    ``None`` *is* the anti-fabrication check. Video needs no separate quote lint.
    """
    full = flatten(cues)
    idx = full.find(quote.strip())
    if idx < 0:
        return None
    consumed = 0
    for start, line in cues:
        consumed += len(line) + 1  # +1 for the joining space
        if consumed > idx:
            return start
    return cues[-1][0] if cues else None


def estimate_tokens(text: str) -> int:
    """~323 tokens per minute of French speech, measured on a 43-minute
    programme: 48,705 characters for 13,915 tokens, i.e. ~3.5 chars/token.
    """
    return round(len(text) / 3.5)
