"""Pure-Python search index (no native dependencies, so it installs instantly on Render's free tier).

Every chunk is searchable by keyword (BM25). If embedding vectors are available (Gemini/OpenAI key set),
results are fused with cosine similarity (reciprocal-rank fusion), otherwise BM25 alone is used.
Data lives in one JSON file; swap this class out if you need durable storage.
"""
import json
import math
import os
import threading
from collections import Counter
from pathlib import Path

from .chunking import Chunk
from .textutil import tokenize

K1, B, RRF_K = 1.5, 0.75, 60


def _unit(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / n, 5) for x in vec]


class VectorStore:
    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._chunks: dict[str, dict] = {}
        if self._path.exists():
            try:
                self._chunks = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._chunks = {}
        for c in self._chunks.values():
            self._index(c)

    @staticmethod
    def _index(c: dict) -> None:
        toks = tokenize(c["text"])
        c["_tf"], c["_len"] = Counter(toks), max(len(toks), 1)

    def _flush(self) -> None:
        slim = {k: {f: v for f, v in c.items() if not f.startswith("_")} for k, c in self._chunks.items()}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(slim))
        os.replace(tmp, self._path)

    # ------------------------------------------------------------------ write
    def add(self, doc_id: str, filename: str, chunks: list[Chunk],
            vectors: list[list[float]] | None = None, vtag: str = "") -> None:
        with self._lock:
            for i, ch in enumerate(chunks):
                rec = {"doc_id": doc_id, "filename": filename, "page": ch.page, "idx": ch.index, "text": ch.text}
                if vectors:
                    rec["vec"], rec["vtag"] = _unit(vectors[i]), vtag
                self._index(rec)
                self._chunks[f"{doc_id}:{ch.index}"] = rec
            self._flush()

    def delete_doc(self, doc_id: str) -> None:
        with self._lock:
            self._chunks = {k: c for k, c in self._chunks.items() if c["doc_id"] != doc_id}
            self._flush()

    # ------------------------------------------------------------------- read
    def _candidates(self, doc_ids: list[str]) -> list[dict]:
        wanted = set(doc_ids)
        return [c for c in self._chunks.values() if not wanted or c["doc_id"] in wanted]

    @staticmethod
    def _public(c: dict, score: float) -> dict:
        return {"doc_id": c["doc_id"], "filename": c["filename"], "page": c["page"],
                "text": c["text"], "score": round(max(0.0, min(1.0, score)), 4)}

    def leads(self, doc_ids: list[str], per_doc: int = 2, limit: int = 6) -> list[dict]:
        """First chunks of each document (used for 'summarise' style questions)."""
        with self._lock:
            by_doc: dict[str, list[dict]] = {}
            for c in self._candidates(doc_ids):
                by_doc.setdefault(c["doc_id"], []).append(c)
            out = []
            for chunks in by_doc.values():
                chunks.sort(key=lambda c: c["idx"])
                out += [self._public(c, 1.0) for c in chunks[:per_doc]]
            return out[:limit]

    def search(self, text: str, vector: list[float] | None, vtag: str, k: int, doc_ids: list[str]) -> list[dict]:
        with self._lock:
            cands = self._candidates(doc_ids)
            if not cands:
                return []
            q_terms = list(dict.fromkeys(tokenize(text)))

            # ---- BM25 + idf-weighted term coverage (the % shown in the UI)
            n = len(cands)
            avgdl = sum(c["_len"] for c in cands) / n
            idf = {}
            for t in q_terms:
                df = sum(1 for c in cands if t in c["_tf"])
                idf[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))
            total_idf = sum(idf.values()) or 1.0
            bm25: dict[int, float] = {}
            coverage: dict[int, float] = {}
            for i, c in enumerate(cands):
                s, cov = 0.0, 0.0
                for t in q_terms:
                    f = c["_tf"].get(t, 0)
                    if f:
                        s += idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * c["_len"] / avgdl))
                        cov += idf[t]
                if s > 0:
                    bm25[i], coverage[i] = s, cov / total_idf
            kw_rank = sorted(bm25, key=bm25.get, reverse=True)

            # ---- cosine (only chunks embedded with the same model as the query)
            cos: dict[int, float] = {}
            if vector:
                q = _unit(vector)
                for i, c in enumerate(cands):
                    if c.get("vtag") == vtag and len(c["vec"]) == len(q):
                        cos[i] = sum(a * b for a, b in zip(q, c["vec"]))
            vec_rank = sorted(cos, key=cos.get, reverse=True)[: max(k * 4, 20)]

            if not vec_rank:
                order = kw_rank[:k]
                return [self._public(cands[i], coverage[i]) for i in order]

            fused: dict[int, float] = {}
            for rank_list in (kw_rank[: max(k * 4, 20)], vec_rank):
                for r, i in enumerate(rank_list):
                    fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
            order = sorted(fused, key=fused.get, reverse=True)[:k]
            return [self._public(cands[i], max(cos.get(i, 0.0), coverage.get(i, 0.0))) for i in order]
