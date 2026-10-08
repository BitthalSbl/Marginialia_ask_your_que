import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { api } from "../api";

const MAX_MB = 15;

export default function Dropzone({ disabled, onUploaded }) {
  const [items, setItems] = useState([]); // {key, name, status: "uploading" | "done" | "error", message}

  const patch = (key, changes) =>
    setItems((list) => list.map((it) => (it.key === key ? { ...it, ...changes } : it)));

  const onDrop = useCallback(
    async (accepted, rejected) => {
      const failed = rejected.map((r, i) => ({
        key: `rej-${Date.now()}-${i}`,
        name: r.file.name,
        status: "error",
        message: r.errors[0]?.code === "file-too-large" ? `Larger than ${MAX_MB} MB` : "Only PDF files are accepted",
      }));
      const queued = accepted.map((f, i) => ({ key: `up-${Date.now()}-${i}`, name: f.name, status: "uploading", file: f }));
      setItems((list) => [...queued.map(({ file, ...rest }) => rest), ...failed, ...list].slice(0, 6));

      for (const { key, file } of queued) {
        try {
          const doc = await api.uploadDoc(file);
          patch(key, { status: "done", message: `${doc.pages} pages indexed` });
          onUploaded(doc);
        } catch (e) {
          patch(key, { status: "error", message: e.message });
        }
      }
    },
    [onUploaded]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled,
    accept: { "application/pdf": [".pdf"] },
    maxSize: MAX_MB * 1024 * 1024,
  });

  return (
    <section aria-label="Add documents">
      <div {...getRootProps({ className: `drop${isDragActive ? " active" : ""}${disabled ? " off" : ""}` })}>
        <input {...getInputProps()} />
        <strong>{isDragActive ? "Drop to index" : "Drop PDFs here"}</strong>
        <span>or click to browse. Up to {MAX_MB} MB each.</span>
      </div>
      {items.length > 0 && (
        <ul className="uploads" aria-live="polite">
          {items.map((it) => (
            <li key={it.key} className={it.status}>
              <span className="name">{it.name}</span>
              <span className="msg">{it.status === "uploading" ? "Reading and embedding…" : it.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
