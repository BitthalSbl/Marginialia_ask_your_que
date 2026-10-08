import { useEffect, useRef, useState } from "react";
import { streamChat } from "../api";

const CITE = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

function Answer({ text, onCite }) {
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    parts.push(text.slice(last, m.index));
    m[1].split(",").forEach((n, i) => {
      const num = Number(n.trim());
      parts.push(
        <button key={`${m.index}-${i}`} className="cite" onClick={() => onCite(num)} aria-label={`Open source ${num}`}>
          {num}
        </button>
      );
    });
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return <p className="answer">{parts}</p>;
}

function Sources({ sources, open, setOpen }) {
  if (!sources?.length) return null;
  return (
    <details className="sources" open={open != null || undefined}>
      <summary>{sources.length} passages used</summary>
      <ol>
        {sources.map((s) => (
          <li key={s.index} className={open === s.index ? "open" : ""}>
            <button className="src-head" onClick={() => setOpen(open === s.index ? null : s.index)} aria-expanded={open === s.index}>
              <span className="src-n">{s.index}</span>
              <span className="src-file">{s.filename}</span>
              <span className="src-page">p. {s.page}</span>
              <span className="src-score">{Math.round(s.score * 100)}% match</span>
            </button>
            {open === s.index && <blockquote>{s.text}</blockquote>}
          </li>
        ))}
      </ol>
    </details>
  );
}

function Message({ msg }) {
  const [open, setOpen] = useState(null);
  if (msg.role === "user") return <div className="turn user"><p>{msg.content}</p></div>;
  return (
    <div className="turn bot">
      {msg.content ? <Answer text={msg.content} onCite={setOpen} /> : msg.streaming && !msg.error && <p className="thinking">Searching the documents…</p>}
      {msg.streaming && msg.content && <span className="caret" aria-hidden="true" />}
      {msg.error && <p className="notice danger">{msg.error}</p>}
      <Sources sources={msg.sources} open={open} setOpen={setOpen} />
    </div>
  );
}

export default function Chat({ selectedIds, hasDocs, ready }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const patchLast = (fn) =>
    setMessages((list) => {
      const copy = list.slice();
      copy[copy.length - 1] = fn(copy[copy.length - 1]);
      return copy;
    });

  const canSend = ready && !busy && input.trim() && selectedIds.length > 0;

  async function send() {
    if (!canSend) return;
    const question = input.trim();
    const history = messages
      .filter((m) => m.content && !m.error)
      .slice(-6)
      .map(({ role, content }) => ({ role, content }));

    setMessages((list) => [
      ...list,
      { role: "user", content: question },
      { role: "assistant", content: "", sources: [], streaming: true },
    ]);
    setInput("");
    setBusy(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamChat({
        question,
        docIds: selectedIds,
        history,
        signal: ctrl.signal,
        onSources: (sources) => patchLast((m) => ({ ...m, sources })),
        onToken: (t) => patchLast((m) => ({ ...m, content: m.content + t })),
        onError: (error) => patchLast((m) => ({ ...m, error })),
      });
    } catch (e) {
      if (e.name !== "AbortError") patchLast((m) => ({ ...m, error: e.message }));
    } finally {
      patchLast((m) => ({ ...m, streaming: false }));
      setBusy(false);
      abortRef.current = null;
    }
  }

  const hint = !hasDocs
    ? "Add a PDF to start asking questions."
    : selectedIds.length === 0
    ? "Tick at least one document under “Search in”."
    : null;

  return (
    <div className="chat">
      <div className="log" role="log" aria-live="polite">
        {messages.length === 0 && (
          <div className="blank">
            <h2>What do you want to know?</h2>
            <p>Answers are written only from the passages found in your selected documents, with the page for each claim.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <Message key={i} msg={m} />
        ))}
        <div ref={endRef} />
      </div>

      <div className="composer">
        {hint && <p className="hint">{hint}</p>}
        <div className="row">
          <textarea
            rows={2}
            value={input}
            placeholder="Ask a question about your documents"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          {busy ? (
            <button className="btn stop" onClick={() => abortRef.current?.abort()}>Stop</button>
          ) : (
            <button className="btn" disabled={!canSend} onClick={send}>Ask</button>
          )}
        </div>
      </div>
    </div>
  );
}
