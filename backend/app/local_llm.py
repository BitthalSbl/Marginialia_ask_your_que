"""Offline 'answer writer': no model, no API key.

It picks the sentences from the retrieved passages that best match the question and quotes them with
[n] citations. Not as fluent as an LLM, but always available, instant, and faithful to the documents.
"""
import asyncio
import math
from collections import Counter
from typing import AsyncIterator

from .textutil import is_summary_request, split_sentences, tokenize

MAX_BULLETS = 5
MAX_LEN = 420


def _clip(s: str) -> str:
    s = " ".join(s.split())
    return s if len(s) <= MAX_LEN else s[: MAX_LEN - 1].rsplit(" ", 1)[0] + "…"


def _sentences(text: str) -> list[str]:
    """Whole sentences only: drop a clipped first fragment (starts lowercase) and an unfinished last one."""
    parts = split_sentences(text)
    if parts and parts[0][0].islower():
        parts = parts[1:]
    if parts and parts[-1][-1] not in ".!?।:":
        parts = parts[:-1]
    return parts


def _dedupe(pairs: list[tuple[int, str]]) -> list[tuple[int, str]]:
    seen, out = set(), []
    for n, s in pairs:
        key = " ".join(s.lower().split())
        if key not in seen:
            seen.add(key)
            out.append((n, s))
    return out


def extractive_answer(question: str, hits: list[dict], note: str = "") -> str:
    if not hits:
        return ("I couldn't find passages matching this question in the selected documents. "
                "Try words that actually appear in the document.")

    if is_summary_request(question):
        picked = []
        for n, h in enumerate(hits, 1):
            for s in (_sentences(h["text"]) or split_sentences(h["text"]))[:2]:
                picked.append((n, s))
        picked = _dedupe(picked)[: MAX_BULLETS + 1]
        head = "Opening of the selected documents:"
    else:
        q_terms = set(tokenize(question))
        sents = _dedupe([(n, s) for n, h in enumerate(hits, 1) for s in _sentences(h["text"])])
        if not sents:
            sents = _dedupe([(n, s) for n, h in enumerate(hits, 1) for s in split_sentences(h["text"])])
        df = Counter(t for _, s in sents for t in set(tokenize(s)) if t in q_terms)
        scored = []
        for pos, (n, s) in enumerate(sents):
            toks = set(tokenize(s))
            overlap = sum(math.log(1 + len(sents) / df[t]) for t in q_terms & toks)
            if overlap > 0:
                rank_bonus = 1 + 0.2 * (len(hits) - n) / len(hits)
                scored.append((overlap * rank_bonus / math.sqrt(len(toks) + 4), pos, n, s))
        scored.sort(reverse=True)
        best = scored[0][0] if scored else 0
        per_hit: Counter = Counter()
        chosen = []
        for score, pos, n, s in scored:
            if score < 0.5 * best:  # drop weak matches so one strong line isn't buried in noise
                break
            if per_hit[n] < 2 and len(chosen) < MAX_BULLETS:
                per_hit[n] += 1
                chosen.append((n, pos, s))
        if not chosen:  # retrieval matched but no sentence did: fall back to the best passage's opening
            chosen = [(1, i, s) for i, s in enumerate((_sentences(hits[0]["text"]) or split_sentences(hits[0]["text"]))[:2])]
        picked = [(n, s) for n, _, s in chosen]  # already best-match first
        head = "Most relevant lines from your documents:"

    if not picked:
        picked = [(1, hits[0]["text"][:MAX_LEN])]
    body = "\n".join(f"• {_clip(s)} [{n}]" for n, s in picked)
    return f"{note}{head}\n\n{body}"


async def stream_text(text: str) -> AsyncIterator[str]:
    """Yield the answer in small pieces so the UI streams like a real model."""
    words = text.split(" ")
    for i in range(0, len(words), 3):
        yield " ".join(words[i : i + 3]) + (" " if i + 3 < len(words) else "")
        await asyncio.sleep(0.012)
