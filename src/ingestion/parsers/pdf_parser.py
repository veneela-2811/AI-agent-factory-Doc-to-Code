from pathlib import Path
from pypdf import PdfReader
from src.ingestion.parsers.base import BaseDocumentParser, ParsedDocument, ParsedSection


class PDFParser(BaseDocumentParser):
    def parse(self, file_path: Path) -> ParsedDocument:
        reader = PdfReader(str(file_path))
        sections = []
        full_text = []

        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            
            full_text.append(text)
            # Group page into logical sections
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            first_line = lines[0] if lines else f"Page {page_idx + 1}"
            title = first_line[:80]

            sections.append(ParsedSection(
                section_id=f"page_{page_idx + 1}",
                title=title,
                level=1,
                page_number=page_idx + 1,
                content=text
            ))

        return ParsedDocument(
            filename=file_path.name,
            doc_type="PDF",
            sections=sections,
            raw_text="\n\n".join(full_text)
        )
