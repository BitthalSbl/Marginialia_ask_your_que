const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

async function failure(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join("; ");
  } catch {
    /* fall through */
  }
  return `Request failed (${res.status})`;
}

async function json(path, options) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) throw new Error(await failure(res));
  return res.status === 204 ? null : res.json();
}

export const api = {
  health: () => json("/api/health"),
  listDocs: () => json("/api/documents"),
  deleteDoc: (id) => json(`/api/documents/${id}`, { method: "DELETE" }),
  uploadDoc: (file) => {
    const form = new FormData();
    form.append("file", file);
    return json("/api/documents", { method: "POST", body: form });
  },
};

/**
 * POST /api/chat and parse the Server-Sent Events stream.
 * EventSource only supports GET, so we read the fetch body stream directly.
 */
export async function streamChat({ question, docIds, history, signal, onSources, onToken, onError }) {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, doc_ids: docIds, history }),
    signal,
  });
  if (!res.ok) throw new Error(await failure(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (block) => {
    let event = "message";
    const data = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return;
    const payload = JSON.parse(data.join("\n"));
    if (event === "sources") onSources?.(payload);
    else if (event === "token") onToken?.(payload.text);
    else if (event === "error") onError?.(payload.message);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      dispatch(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
    }
  }
}
