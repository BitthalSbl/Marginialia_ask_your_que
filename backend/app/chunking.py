from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int
    index: int


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Greedy splitter that prefers paragraph, then line, then sentence boundaries."""
    if overlap >= size:
        raise ValueError("chunk overlap must be smaller than chunk size")
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
            if cut > size * 0.6:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        nxt = max(end - overlap, start + 1)
        window = text[nxt:end]  # begin the next chunk at a sentence boundary inside the overlap, if any
        for sep in ("\n", ". "):
            at = window.find(sep)
            if at != -1:
                nxt += at + len(sep)
                break
        start = min(nxt, end)
    return pieces


def build_chunks(pages: list[tuple[int, str]], size: int, overlap: int) -> list[Chunk]:
    """Chunk page by page so every chunk keeps an exact page number for citations."""
    chunks: list[Chunk] = []
    for page, text in pages:
        for piece in split_text(text, size, overlap):
            if len(piece) >= 30:
                chunks.append(Chunk(piece, page, len(chunks)))
    return chunks
