import json
import os
import threading
from pathlib import Path


class Registry:
    """Tiny JSON-backed catalogue of uploaded documents (one file, atomic writes)."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._docs: dict[str, dict] = {}
        if self._path.exists():
            try:
                self._docs = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._docs = {}

    def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._docs))
        os.replace(tmp, self._path)

    def list(self) -> list[dict]:
        with self._lock:
            return sorted(self._docs.values(), key=lambda d: d["created_at"], reverse=True)

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            return self._docs.get(doc_id)

    def add(self, record: dict) -> None:
        with self._lock:
            self._docs[record["id"]] = record
            self._flush()

    def remove(self, doc_id: str) -> None:
        with self._lock:
            self._docs.pop(doc_id, None)
            self._flush()
