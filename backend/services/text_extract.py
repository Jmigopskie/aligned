import os

from docx import Document

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# Was 20,000, which kept about a tenth of the 184-page MATATAG curriculum guide
# and so most of its standards and competencies never reached the AI. Now just
# a guard against a pathological file; the column is MEDIUMTEXT on MySQL.
MAX_CHARS = 1_000_000

def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".docx", ".dotx"):
        return _extract_docx(file_path)
    if ext == ".pdf":
        return _extract_pdf(file_path)
    return ""

def _extract_docx(file_path: str) -> str:
    doc = Document(file_path)
    chunks = []

    for para in doc.paragraphs:
        if para.text.strip():
            chunks.append(para.text.strip())

    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                chunks.append(" | ".join(cells))

    for section in doc.sections:
        for container in (section.header, section.footer):
            for para in container.paragraphs:
                if para.text.strip():
                    chunks.append(para.text.strip())

    chunks.extend(_extract_textbox_text(doc))

    seen = set()
    deduped = []
    for c in chunks:
        if c not in seen:
            seen.add(c)
            deduped.append(c)

    return "\n".join(deduped)[:MAX_CHARS]

def _extract_textbox_text(doc) -> list:
    try:
        xml = doc.element.xml
    except Exception:
        return []

    import re

    matches = re.findall(r"<w:txbxContent[^>]*>(.*?)</w:txbxContent>", xml, re.DOTALL)
    texts = []
    for block in matches:
        text_runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", block)
        joined = "".join(text_runs).strip()
        if joined:
            texts.append(joined)
    return texts

def _extract_pdf(file_path: str) -> str:
    if PdfReader is None:
        return ""

    reader = PdfReader(file_path)
    chunks = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())

    return "\n".join(chunks)[:MAX_CHARS]
