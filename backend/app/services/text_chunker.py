import re
from typing import Any


def clean_text(text: str) -> str:
    """Normalizes whitespace and excessive line breaks."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_major_section_start(text: str) -> bool:
    """Detects if a paragraph starts with a major heading or divider."""
    first_line = text.strip().split("\n")[0].strip()
    if re.match(r"^[-=_*~#]{3,}$", first_line):
        return True
    if re.match(r"^#{1,6}\s+", first_line):
        return True
    if re.match(r"^\d+[\.\)]\s+[A-Z]", first_line):
        return True
    return False


def extract_chunk_title(content: str, default_title: str = "Knowledge Section") -> str:
    """
    Intelligently extracts titles from Markdown (# Header), numbered sections
    ('1. SHIPPING POLICY'), or ALL-CAPS topic headers ('DELIVERY CHARGES:').
    Ignores divider lines (===, ---).
    """
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    if not lines:
        return default_title

    # Filter out divider lines (===, ---, ***)
    clean_lines = [l for l in lines if not re.match(r"^[-=_*~#]{3,}$", l)]
    if not clean_lines:
        return default_title

    # 1. Markdown headers (# Header)
    for line in clean_lines:
        m = re.match(r"^#{1,6}\s*(.+)$", line)
        if m and len(m.group(1).strip()) >= 3:
            return m.group(1).strip()[:80]

    # 2. Numbered section headers (e.g. '1. SHIPPING & DELIVERY POLICY')
    for line in clean_lines:
        m = re.match(r"^\d+[\.\)]\s+([A-Za-z0-9\s&/,\-]+)$", line)
        if m:
            return m.group(1).strip()[:80].title()

    # 3. Capitalized topic headings (e.g. 'DELIVERY TIMELINES & CHARGES:')
    for line in clean_lines:
        m = re.match(r"^([A-Z0-9\s&/\-]{4,}):?$", line)
        if m and len(m.group(1).strip()) > 3:
            return m.group(1).strip().title()[:80]

    # 4. Option headings (e.g. 'OPTION A: VIA COURIER / ONLINE')
    for line in clean_lines:
        m = re.match(r"^(OPTION\s+[A-Z0-9]+:?\s*.+)$", line, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:80].title()

    # 5. First meaningful line that does not start with lowercase or bullet point
    for line in clean_lines:
        if line.startswith(("-", "*", "•", "—", "_")):
            continue
        if line[0].islower():
            continue
        clean_line = line.split(". ")[0].strip()
        if len(clean_line) >= 5:
            return clean_line[:80]

    return default_title


def chunk_text(
    text: str,
    chunk_size: int = 750,
    chunk_overlap: int = 100,
    doc_title: str | None = None,
) -> list[dict[str, str]]:
    """
    Splits text into overlapping, semantically coherent chunks with clean section titles.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        title = extract_chunk_title(cleaned, default_title=doc_title or "Overview")
        return [{"title": title, "content": cleaned}]

    paragraphs = cleaned.split("\n\n")
    chunks: list[dict[str, str]] = []
    current_chunk = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # If this paragraph is a brand-new major section, start a fresh chunk
        if is_major_section_start(paragraph) and len(current_chunk) > 200:
            title = extract_chunk_title(current_chunk, default_title=doc_title or f"Section {len(chunks) + 1}")
            chunks.append({"title": title, "content": current_chunk})
            current_chunk = paragraph
            continue

        if len(current_chunk) + len(paragraph) + 2 <= chunk_size:
            current_chunk = f"{current_chunk}\n\n{paragraph}".strip() if current_chunk else paragraph
        else:
            if current_chunk:
                title = extract_chunk_title(current_chunk, default_title=doc_title or f"Section {len(chunks) + 1}")
                chunks.append({"title": title, "content": current_chunk})
                current_chunk = paragraph
            else:
                current_chunk = paragraph

    if current_chunk:
        title = extract_chunk_title(current_chunk, default_title=doc_title or f"Section {len(chunks) + 1}")
        chunks.append({"title": title, "content": current_chunk})

    return chunks