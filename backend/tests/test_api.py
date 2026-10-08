"""End-to-end tests. No network, no API keys, no Docker: runs in the default offline mode."""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(LLM_PROVIDER="auto", GEMINI_API_KEY="", OPENAI_API_KEY="", DATA_DIR=_tmp,
                  CHUNK_SIZE="300", CHUNK_OVERLAP="50")

from fastapi.testclient import TestClient  # noqa: E402

from app import providers  # noqa: E402
from app.chunking import split_text  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


def make_pdf(pages: list[str]) -> bytes:
    objs, kids = [], []
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode()
        base = 4 + i * 2
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {base + 1} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(f"{base} 0 R")
    head = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for n, body in enumerate(head + objs, 1):
        offs.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(offs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(offs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out



def read_stream(c, **body):
    """Return the raw SSE body with the streamed token pieces re-joined, so phrases can be asserted on."""
    import json
    with c.stream("POST", "/api/chat", json=body) as s:
        assert s.status_code == 200, s.read()
        raw = "".join(s.iter_text())
    tokens = [json.loads(line[5:])["text"] for block in raw.split("\n\n") if block.startswith("event: token")
              for line in block.split("\n") if line.startswith("data:")]
    return raw + "\n" + "".join(tokens)


PDF = make_pdf([
    "Photosynthesis converts sunlight into chemical energy in plants. It happens in the chloroplasts of leaf cells.",
    "Mitochondria produce ATP, which cells use as their main energy currency. They are called the powerhouse of the cell.",
])


def test_split_text_overlaps_and_terminates():
    text = ("Sentence number one is here. " * 60).strip()
    parts = split_text(text, 300, 50)
    assert len(parts) > 3 and all(len(p) <= 300 for p in parts)


def test_offline_mode_needs_no_key():
    assert get_settings().provider == "local"
    with TestClient(app) as c:
        h = c.get("/api/health").json()
        assert h["status"] == "ok" and h["provider"] == "local"

        r = c.post("/api/documents", files={"file": ("bio.pdf", PDF, "application/pdf")})
        assert r.status_code == 201, r.text
        doc = r.json()
        assert doc["pages"] == 2 and doc["search"] == "keyword"
        assert c.post("/api/documents", files={"file": ("bio.pdf", PDF, "application/pdf")}).json()["id"] == doc["id"]
        assert c.post("/api/documents", files={"file": ("x.pdf", b"nope", "application/pdf")}).status_code == 415
        assert len(c.get("/api/documents").json()["documents"]) == 1

        body = read_stream(c, question="What produces ATP in cells?", doc_ids=[doc["id"]])
        assert "event: sources" in body and "event: done" in body and "event: error" not in body
        assert "ATP" in body and "[1]" in body

        # Hinglish question still finds the right page
        body = read_stream(c, question="photosynthesis kya hai?", doc_ids=[doc["id"]])
        assert "chloroplasts" in body

        # summary-style question has no keyword overlap but still works
        assert "Opening of the selected documents" in read_stream(c, question="Summarise this", doc_ids=[doc["id"]])

        # unrelated question: honest "not found", not a crash
        assert "couldn't find" in read_stream(c, question="quantum chromodynamics", doc_ids=[doc["id"]])

        assert c.post("/api/chat", json={"question": "hi", "doc_ids": ["nope"]}).status_code == 404
        assert c.delete(f"/api/documents/{doc['id']}").status_code == 204
        assert c.get("/api/documents").json()["documents"] == []


def test_ai_provider_failure_falls_back_to_offline(monkeypatch):
    """A key is set but the provider is down / out of quota: everything still works."""
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "bad-key")
    assert s.provider == "gemini"

    async def boom(*_a, **_k):
        raise providers.ProviderError("Model provider returned 429: quota exceeded")

    async def boom_stream(*_a, **_k):
        raise providers.ProviderError("Model provider returned 429: quota exceeded")
        yield  # pragma: no cover

    monkeypatch.setattr(providers, "embed_documents", boom)
    monkeypatch.setattr(providers, "embed_query", boom)
    monkeypatch.setattr(providers, "stream_chat", boom_stream)

    other = make_pdf(["Rendering pipelines transform scene geometry into pixels on the screen."])
    with TestClient(app) as c:
        r = c.post("/api/documents", files={"file": ("gfx.pdf", other, "application/pdf")})
        assert r.status_code == 201 and r.json()["search"] == "keyword"
        body = read_stream(c, question="How are pixels produced?", doc_ids=[r.json()["id"]])
        assert "unavailable" in body and "pixels" in body and "event: error" not in body


def test_ai_provider_hybrid_path(monkeypatch):
    import hashlib, math, re

    def vec(text, dim=64):
        v = [0.0] * dim
        for w in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def docs(_c, texts):
        return [vec(t) for t in texts]

    async def query(_c, text):
        return vec(text)

    async def stream(_c, system, messages):
        for tok in ["From the ", "passage [1]."]:
            yield tok

    monkeypatch.setattr(get_settings(), "gemini_api_key", "k")
    monkeypatch.setattr(providers, "embed_documents", docs)
    monkeypatch.setattr(providers, "embed_query", query)
    monkeypatch.setattr(providers, "stream_chat", stream)

    other = make_pdf(["Glaciers store most of the planet's fresh water in frozen form."])
    with TestClient(app) as c:
        r = c.post("/api/documents", files={"file": ("ice.pdf", other, "application/pdf")})
        assert r.json()["search"] == "semantic"
        body = read_stream(c, question="Where is fresh water stored?", doc_ids=[r.json()["id"]])
        assert "From the " in body and "event: error" not in body
