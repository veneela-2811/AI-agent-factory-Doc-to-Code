from pathlib import Path
from docx import Document as DocxDoc
from src.ingestion.parsers.base import BaseDocumentParser, ParsedDocument, ParsedSection


class DocxParser(BaseDocumentParser):
    def parse(self, file_path: Path) -> ParsedDocument:
        doc = DocxDoc(str(file_path))
        sections = []
        current_title = "Introduction"
        current_level = 1
        current_content = []
        sec_idx = 1

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            style_name = para.style.name.lower()
            if "heading" in style_name:
                if current_content:
                    sections.append(ParsedSection(
                        section_id=f"sec_{sec_idx}",
                        title=current_title,
                        level=current_level,
                        content="\n".join(current_content)
                    ))
                    sec_idx += 1
                    current_content = []
                
                current_title = text
                try:
                    current_level = int(style_name.replace("heading", "").strip())
                except Exception:
                    current_level = 1
            else:
                current_content.append(text)

        if current_content:
            sections.append(ParsedSection(
                section_id=f"sec_{sec_idx}",
                title=current_title,
                level=current_level,
                content="\n".join(current_content)
            ))

        # If no headings found, treat whole doc as one section
        if not sections and doc.paragraphs:
            sections.append(ParsedSection(
                section_id="sec_1",
                title="Document Body",
                level=1,
                content="\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            ))

        raw_text = "\n\n".join([s.content for s in sections])
        return ParsedDocument(
            filename=file_path.name,
            doc_type="DOCX",
            sections=sections,
            raw_text=raw_text
        )
