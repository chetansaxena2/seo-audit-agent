"""Pure-python text utilities: tokenisation, keyword extraction, duplicate
content detection. No heavy ML dependencies so the container stays small."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Iterable

WORD_RE = re.compile(r"[a-z0-9][a-z0-9'&+-]*", re.I)

STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below
between both but by can cannot could couldn't did didn't do does doesn't doing don't down during each few
for from further had hadn't has hasn't have haven't having he her here hers herself him himself his how i
if in into is isn't it its itself let's me more most mustn't my myself no nor not of off on once only or
other ought our ours ourselves out over own same shan't she should shouldn't so some such than that the
their theirs them themselves then there these they this those through to too under until up very was wasn't
we were weren't what when where which while who whom why with won't would wouldn't you your yours yourself
yourselves get got also may might will just new best top read more click here home page site website us
""".split())

GENERIC_IMG_RE = re.compile(
    r"^(img|image|dsc|photo|pic|untitled|screenshot|download|banner|logo\d*|\d+)[-_ ]?\d*$", re.I
)

QUESTION_RE = re.compile(
    r"^\s*(what|why|how|when|where|who|which|can|do|does|is|are|should|will|would|might)\b", re.I
)


def tokens(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "")]


def content_tokens(text: str) -> list[str]:
    return [w for w in tokens(text) if w not in STOPWORDS and len(w) > 2]


def ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def contains_phrase(haystack: str, phrase: str, fuzzy: bool = True) -> bool:
    """True if the phrase appears, exactly or (optionally) as all its words."""
    h, p = normalize(haystack), normalize(phrase)
    if not h or not p:
        return False
    if p in h:
        return True
    if not fuzzy:
        return False
    parts = [w for w in p.split() if w not in STOPWORDS]
    return bool(parts) and all(w in h for w in parts)


def phrase_count(haystack: str, phrase: str) -> int:
    h, p = normalize(haystack), normalize(phrase)
    if not h or not p:
        return 0
    return h.count(p)


def extract_keywords(text: str, top: int = 25) -> list[tuple[str, int]]:
    """Frequency-ranked 1-3 word phrases, filtered for stopword noise."""
    words = tokens(text)
    scored: Counter[str] = Counter()
    for w, c in Counter(w for w in words if w not in STOPWORDS and len(w) > 2).items():
        scored[w] += c
    for n in (2, 3):
        for g, c in Counter(ngrams(words, n)).items():
            parts = g.split()
            if parts[0] in STOPWORDS or parts[-1] in STOPWORDS:
                continue
            if sum(1 for p in parts if p in STOPWORDS) > len(parts) - 2:
                continue
            if c > 1:
                scored[g] += c * (n + 1)  # favour longer phrases
    return scored.most_common(top)


def shingles(text: str, k: int = 8) -> set[str]:
    words = content_tokens(text)
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {
        hashlib.md5(" ".join(words[i:i + k]).encode()).hexdigest()[:16]
        for i in range(0, len(words) - k + 1)
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def readability(text: str) -> float:
    """Flesch reading ease, approximated (higher = easier)."""
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    words = tokens(text)
    if not words:
        return 0.0
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w))) for w in words)
    return round(
        206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words)), 1
    )


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def is_generic_filename(name: str) -> bool:
    stem = re.sub(r"\.[a-z0-9]{2,5}$", "", name or "", flags=re.I)
    return bool(GENERIC_IMG_RE.match(stem))


def is_question(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and (t.endswith("?") or bool(QUESTION_RE.match(t)))


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        k = normalize(i)
        if k and k not in seen:
            seen.add(k)
            out.append(i)
    return out
