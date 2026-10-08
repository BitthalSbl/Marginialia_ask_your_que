import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Dropzone from "./components/Dropzone.jsx";
import DocSelector from "./components/DocSelector.jsx";
import Chat from "./components/Chat.jsx";

export default function App() {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [server, setServer] = useState("checking"); // checking | waking | ready | down
  const [problem, setProblem] = useState("");
  const [provider, setProvider] = useState("");

  const refresh = useCallback(async () => {
    const { documents } = await api.listDocs();
    setDocs(documents);
    setSelected((prev) => {
      const ids = new Set(documents.map((d) => d.id));
      return new Set([...prev].filter((id) => ids.has(id)));
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Render's free tier sleeps after inactivity; tell people why the first load is slow.
    const timer = setTimeout(() => setServer((s) => (s === "checking" ? "waking" : s)), 2500);
    (async () => {
      try {
        const h = await api.health();
        if (!cancelled) setProvider(h.provider);
        await refresh();
        if (!cancelled) setServer("ready");
      } catch (e) {
        if (!cancelled) {
          setServer("down");
          setProblem(e.message);
        }
      } finally {
        clearTimeout(timer);
      }
    })();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [refresh]);

  const handleUploaded = (doc) => {
    setSelected((prev) => new Set(prev).add(doc.id));
    refresh().catch(() => {});
  };

  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const remove = async (id) => {
    await api.deleteDoc(id);
    await refresh();
  };

  return (
    <div className="shell">
      <aside className="rail">
        <header className="brand">
          <h1>Marginalia</h1>
          <p>Ask your PDFs. Every answer points to the page.</p>
          {provider && (
            <p className="mode">
              {provider === "local" ? "Offline mode · no API key needed" : `AI mode · ${provider}`}
            </p>
          )}
        </header>

        {server === "waking" && (
          <p className="notice">The server is waking up. The first request can take about a minute.</p>
        )}
        {server === "down" && (
          <p className="notice danger">Can't reach the API: {problem}. Try again in a minute; the free server may still be starting.</p>
        )}

        <Dropzone disabled={server !== "ready"} onUploaded={handleUploaded} />
        <DocSelector
          docs={docs}
          selected={selected}
          onToggle={toggle}
          onSelectAll={(all) => setSelected(all ? new Set(docs.map((d) => d.id)) : new Set())}
          onDelete={remove}
        />
      </aside>

      <main className="stage">
        <Chat selectedIds={[...selected]} hasDocs={docs.length > 0} ready={server === "ready"} />
      </main>
    </div>
  );
}
