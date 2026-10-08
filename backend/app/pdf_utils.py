import io
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError


class PdfError(ValueError):
    """Raised when a PDF cannot be read."""


def _join_wrapped_lines(text: str) -> str:
    """PDFs emit a newline at every visual line wrap. Re-join those so sentences stay whole, but keep
    headings, bullets and paragraph breaks: a line is a wrap if it doesn't end a sentence and either the
    next line starts lowercase or the line is long (full-width lines wrap, headings are short)."""
    lines = text.split("\n")
    out = [lines[0]] if lines else []
    for nxt in lines[1:]:
        prev = out[-1]
        if prev.strip() and nxt.strip() and prev.rstrip()[-1] not in ".!?:;।" and not re.match(r"\s*([•\-*]|\d+[.)])\s", nxt) \
                and (nxt.lstrip()[0].islower() or len(prev.strip()) >= 50):
            out[-1] = prev.rstrip() + " " + nxt.lstrip()
        else:
            out.append(nxt)
    return "\n".join(out)


def _clean(text: str) -> str:
    text = text.replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)        # re-join hyphenated line breaks
    text = _join_wrapped_lines(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(data: bytes) -> list[tuple[int, str]]:
    """Return [(page_number, text)] for pages that contain extractable text."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfError("This PDF is password-protected.")
        pages: list[tuple[int, str]] = []
        for number, page in enumerate(reader.pages, start=1):
            text = _clean(page.extract_text() or "")
            if text:
                pages.append((number, text))
        return pages
    except PdfError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError) as exc:
        raise PdfError(f"Could not read this PDF: {exc}") from exc
