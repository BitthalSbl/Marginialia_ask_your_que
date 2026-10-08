"""Embedding + chat-completion clients for Gemini and OpenAI (plain REST via httpx).

Using REST keeps the Docker image small and the streaming code explicit.
"""
import asyncio
import json
from typing import AsyncIterator

import httpx

from .config import get_settings

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_BASE = "https://api.openai.com/v1"
RETRY_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """Upstream model provider failure (surfaced to the client as a 502 / SSE error)."""


def _explain(status: int, body: bytes | str) -> str:
    raw = body.decode("utf-8", "ignore") if isinstance(body, bytes) else body
    try:
        message = json.loads(raw).get("error", {}).get("message") or raw
    except (json.JSONDecodeError, AttributeError):
        message = raw
    return f"Model provider returned {status}: {message[:300]}"


def _headers() -> dict[str, str]:
    s = get_settings()
    if s.provider == "gemini":
        return {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {s.openai_api_key}", "Content-Type": "application/json"}


async def _post(client: httpx.AsyncClient, url: str, payload: dict, retries: int = 4) -> httpx.Response:
    delay = 1.5
    for attempt in range(retries + 1):
        try:
            resp = await client.post(url, headers=_headers(), json=payload)
        except httpx.HTTPError as exc:
            if attempt == retries:
                raise ProviderError(f"Could not reach the model provider: {exc}") from exc
            await asyncio.sleep(delay)
            delay *= 2
            continue
        if resp.status_code in RETRY_STATUS and attempt < retries:
            await asyncio.sleep(delay)
            delay *= 2
            continue
        if resp.status_code >= 400:
            raise ProviderError(_explain(resp.status_code, resp.content))
        return resp
    raise ProviderError("Model provider is unavailable.")  # pragma: no cover


# ---------------------------------------------------------------- embeddings
async def _embed(client: httpx.AsyncClient, texts: list[str], task: str) -> list[list[float]]:
    s = get_settings()
    vectors: list[list[float]] = []
    if s.provider == "gemini":
        model = s.gemini_embed_model
        url = f"{GEMINI_BASE}/models/{model}:batchEmbedContents"
        for i in range(0, len(texts), 100):
            payload = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": t}]},
                        "taskType": task,
                        "outputDimensionality": s.gemini_embed_dim,
                    }
                    for t in texts[i : i + 100]
                ]
            }
            data = (await _post(client, url, payload)).json()
            vectors += [e["values"] for e in data["embeddings"]]
    else:
        for i in range(0, len(texts), 96):
            payload = {"model": s.openai_embed_model, "input": texts[i : i + 96]}
            data = (await _post(client, f"{OPENAI_BASE}/embeddings", payload)).json()
            vectors += [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    return vectors


async def embed_documents(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    return await _embed(client, texts, "RETRIEVAL_DOCUMENT")


async def embed_query(client: httpx.AsyncClient, text: str) -> list[float]:
    return (await _embed(client, [text], "RETRIEVAL_QUERY"))[0]


# ------------------------------------------------------------------ streaming
async def stream_chat(
    client: httpx.AsyncClient, system: str, messages: list[dict[str, str]]
) -> AsyncIterator[str]:
    """Yield answer text fragments as the provider generates them."""
    s = get_settings()
    if s.provider == "gemini":
        url = f"{GEMINI_BASE}/models/{s.gemini_chat_model}:streamGenerateContent?alt=sse"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages
            ],
            "generationConfig": {"temperature": 0.2},
        }
    else:
        url = f"{OPENAI_BASE}/chat/completions"
        payload = {
            "model": s.openai_chat_model,
            "stream": True,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, *messages],
        }

    async with client.stream("POST", url, headers=_headers(), json=payload) as resp:
        if resp.status_code >= 400:
            raise ProviderError(_explain(resp.status_code, await resp.aread()))
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if not body or body == "[DONE]":
                continue
            data = json.loads(body)
            if s.provider == "gemini":
                if data.get("promptFeedback", {}).get("blockReason") and not data.get("candidates"):
                    raise ProviderError("The request was blocked by the model's safety filters.")
                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if part.get("text"):
                            yield part["text"]
            else:
                for choice in data.get("choices", []):
                    text = choice.get("delta", {}).get("content")
                    if text:
                        yield text
