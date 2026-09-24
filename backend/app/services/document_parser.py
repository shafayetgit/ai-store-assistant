import io
import logging
from pathlib import Path
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """
    Extracts plain text from raw file bytes supporting PDF, TXT, and Markdown.

    Args:
        file_bytes: The raw binary content of the uploaded file.
        filename: The original name of the file (used to inspect extension).

    Returns:
        Clean, extracted string content.

    Raises:
        ValueError: If the file extension is unsupported or no readable text was found.
    """
    ext = Path(filename).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format '{ext}'. Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    text = ""

    if ext == ".pdf":
        try:
            # Open PDF directly from in-memory byte stream
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                pages_text: list[str] = []
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    page_text = page.get_text("text").strip()
                    if page_text:
                        pages_text.append(page_text)

                text = "\n\n".join(pages_text)
        except Exception as exc:
            logger.error(f"Failed to parse PDF '{filename}': {exc}", exc_info=True)
            raise ValueError(f"Failed to read PDF document: {exc}") from exc

    elif ext in {".txt", ".md"}:
        try:
            text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            # Fallback to Latin-1 if UTF-8 fails
            try:
                text = file_bytes.decode("latin-1").strip()
            except Exception as exc:
                raise ValueError(f"Could not decode text file: {exc}") from exc

    if not text.strip():
        raise ValueError(
            f"The uploaded document '{filename}' contains no readable text. "
            "(If it is a scanned PDF, please run OCR first)."
        )

    return text.strip()