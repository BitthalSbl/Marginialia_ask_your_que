import { useState } from "react";

export default function DocSelector({ docs, selected, onToggle, onSelectAll, onDelete }) {
  const [error, setError] = useState("");
  const allOn = docs.length > 0 && selected.size === docs.length;

  const del = async (doc) => {
    if (!window.confirm(`Remove "${doc.filename}" and its index?`)) return;
    try {
      setError("");
      await onDelete(doc.id);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <section className="docs" aria-label="Documents to search">
      <div className="docs-head">
        <h2>Search in</h2>
        {docs.length > 1 && (
          <button className="link" onClick={() => onSelectAll(!allOn)}>
            {allOn ? "Clear" : "Select all"}
          </button>
        )}
      </div>

      {docs.length === 0 ? (
        <p className="empty">No documents yet. Add a PDF to begin.</p>
      ) : (
        <ul>
          {docs.map((d) => (
            <li key={d.id}>
              <label>
                <input type="checkbox" checked={selected.has(d.id)} onChange={() => onToggle(d.id)} />
                <span className="doc-name">{d.filename}</span>
                <span className="doc-meta">{d.pages} pages</span>
              </label>
              <button className="icon" aria-label={`Remove ${d.filename}`} onClick={() => del(d)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="notice danger">{error}</p>}
    </section>
  );
}
