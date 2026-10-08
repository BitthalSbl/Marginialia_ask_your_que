import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import local_llm, providers, rag
from .chunking import build_chunks
from .config import get_settings
from .pdf_utils import PdfError, extract_pages
from .textutil import is_summary_request
from .registry import Registry
from .vectorstore import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rag")

settings = get_settings()
# One index shared by all modes: chunks always keep their text (keyword search works everywhere);
# vectors are optional and tagged with the model that made them.
store = VectorStore(f"{settings.data_dir}/index.json")
registry = Registry(f"{settings.data_dir}/registry.json")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"  # pre-built frontend


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0))
    yield
    await app.state.http.aclose()


app = FastAPI(title="Marginalia RAG API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_origin_regex=settings.allowed_origin_regex or None,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.exception_handler(providers.ProviderError)
async def provider_error_handler(_: Request, exc: providers.ProviderError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# ------------------------------------------------------------------ health
@app.get("/api/health")
async def health():
    return {"status": "ok", "provider": settings.provider, "documents": len(registry.list())}


# --------------------------------------------------------------- documents
@app.get("/api/documents")
async def list_documents():
    return {"documents": registry.list()}


@app.post("/api/documents", status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...)):
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"PDF is larger than {settings.max_upload_mb} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Only PDF files are supported.")

    doc_id = hashlib.sha256(data).hexdigest()[:16]
    if existing := registry.get(doc_id):
        return existing  # identical file already indexed

    try:
        pages = await run_in_threadpool(extract_pages, data)
    except PdfError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not pages:
        raise HTTPException(422, "No extractable text found. Scanned PDFs need OCR first.")

    chunks = build_chunks(pages, settings.chunk_size, settings.chunk_overlap)
    if len(chunks) > settings.max_chunks_per_doc:
        raise HTTPException(
            413, f"Document produced {len(chunks)} chunks; the limit is {settings.max_chunks_per_doc}."
        )

    filename = file.filename or "document.pdf"
    vectors, mode = None, "keyword"
    if settings.provider != "local":
        try:
            vectors = await providers.embed_documents(request.app.state.http, [c.text for c in chunks])
            mode = "semantic"
        except providers.ProviderError as exc:  # quota / network: still index for keyword search
            log.warning("embedding failed, indexing for keyword search only: %s", exc)
    await run_in_threadpool(store.add, doc_id, filename, chunks, vectors, settings.embed_tag)

    record = {
        "id": doc_id,
        "filename": filename,
        "pages": len(pages),
        "chunks": len(chunks),
        "size_bytes": len(data),
        "search": mode,
        "created_at": time.time(),
    }
    registry.add(record)
    log.info("indexed %s (%d pages, %d chunks)", filename, len(pages), len(chunks))
    return record


@app.delete("/api/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: str):
    if not registry.get(doc_id):
        raise HTTPException(404, "Document not found.")
    await run_in_threadpool(store.delete_doc, doc_id)
    registry.remove(doc_id)


# -------------------------------------------------------------------- chat
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    doc_ids: list[str] = Field(default_factory=list, max_length=50)
    top_k: int | None = Field(default=None, ge=1, le=50)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)


def sse(event: str, data: dict | list) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    missing = [d for d in req.doc_ids if not registry.get(d)]
    if missing:
        raise HTTPException(404, f"Unknown document id(s): {', '.join(missing)}")
    if not registry.list():
        raise HTTPException(400, "Upload a PDF before asking questions.")

    top_k = min(req.top_k or settings.top_k_default, settings.top_k_max)
    history = [m.model_dump() for m in req.history]
    client: httpx.AsyncClient = request.app.state.http

    async def event_stream():
        try:
            provider = settings.provider
            query = rag.retrieval_query(req.question, history)
            if is_summary_request(req.question):
                hits = await run_in_threadpool(store.leads, req.doc_ids)
            else:
                qvec = None
                if provider != "local":
                    try:
                        qvec = await providers.embed_query(client, query)
                    except providers.ProviderError as exc:
                        log.warning("query embedding failed, using keyword search: %s", exc)
                hits = await run_in_threadpool(store.search, query, qvec, settings.embed_tag, top_k, req.doc_ids)
            yield sse("sources", [{"index": i, **h} for i, h in enumerate(hits, 1)])

            if not hits:
                yield sse("token", {"text": local_llm.extractive_answer(req.question, [])})
                yield sse("done", {})
                return

            started = False
            if provider != "local":
                try:
                    messages = rag.build_messages(history, rag.build_user_prompt(req.question, hits))
                    async for piece in providers.stream_chat(client, rag.SYSTEM_PROMPT, messages):
                        if await request.is_disconnected():
                            return
                        started = True
                        yield sse("token", {"text": piece})
                    yield sse("done", {})
                    return
                except providers.ProviderError as exc:
                    if started:
                        raise
                    log.warning("model call failed, answering offline: %s", exc)
                    note = "(The AI model is unavailable right now, so these are matching lines instead.)\n\n"
            else:
                note = ""

            answer = local_llm.extractive_answer(req.question, hits, note)
            async for piece in local_llm.stream_text(answer):
                if await request.is_disconnected():
                    return
                yield sse("token", {"text": piece})
            yield sse("done", {})
        except providers.ProviderError as exc:
            yield sse("error", {"message": str(exc)})
        except Exception:  # noqa: BLE001 - never leak internals over the stream
            log.exception("chat stream failed")
            yield sse("error", {"message": "Unexpected server error."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# Serve the pre-built React app from the same origin (no CORS or VITE_API_URL to configure).
# Mounted last so every /api route above wins.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
