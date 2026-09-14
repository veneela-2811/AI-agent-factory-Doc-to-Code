import os
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from config.settings import settings
from src.storage.models import Document, DocumentSection
from src.storage.vector_store import vector_store
from src.ingestion.parsers.base import BaseDocumentParser, ParsedDocument
from src.ingestion.parsers.pdf_parser import PDFParser
from src.ingestion.parsers.docx_parser import DocxParser
from src.ingestion.parsers.other_parsers import PPTXParser, XLSXParser, TextParser

logger = logging.getLogger("ingestion_pipeline")


class DocumentIngestionPipeline:
    def __init__(self):
        self.parsers: Dict[str, BaseDocumentParser] = {
            ".pdf": PDFParser(),
            ".docx": DocxParser(),
            ".pptx": PPTXParser(),
            ".xlsx": XLSXParser(),
            ".md": TextParser(),
            ".txt": TextParser(),
        }

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += (chunk_size - overlap)
        return chunks

    async def process_document(
        self,
        project_id: str,
        document_id: str,
        file_path: Path,
        db: AsyncSession
    ) -> None:
        logger.info(f"Starting ingestion for doc {document_id} ({file_path.name})")
        ext = file_path.suffix.lower()
        parser = self.parsers.get(ext)
        if not parser:
            parser = TextParser()

        # Fetch document record
        result = await db.execute(
            select(Document).where(Document.id == document_id, Document.project_id == project_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            logger.error(f"Document {document_id} not found in database")
            return

        try:
            doc.status = "parsing"
            await db.commit()

            parsed_doc = parser.parse(file_path)
            
            all_chunks = []
            section_records = []

            for sec in parsed_doc.sections:
                chunks = self._chunk_text(sec.content, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
                for c_idx, chunk_text in enumerate(chunks):
                    sec_rec = DocumentSection(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        project_id=project_id,
                        section_id=sec.section_id,
                        title=sec.title,
                        level=sec.level,
                        page_number=sec.page_number,
                        content=chunk_text,
                        chunk_index=c_idx
                    )
                    section_records.append(sec_rec)

                    all_chunks.append({
                        "section_id": sec.section_id,
                        "title": sec.title,
                        "page_number": sec.page_number,
                        "chunk_index": c_idx,
                        "content": chunk_text,
                        "kind": "BRD" if "brd" in file_path.name.lower() else "PRD"
                    })

            # Save section records to SQLite
            db.add_all(section_records)

            # Upsert chunks into ChromaDB with project_id isolation
            vector_store.upsert_document_chunks(
                project_id=project_id,
                document_id=document_id,
                chunks=all_chunks
            )

            # Update Document status
            doc.status = "ready"
            doc.section_count = len(parsed_doc.sections)
            doc.chunk_count = len(all_chunks)
            doc.error_message = None
            await db.commit()
            logger.info(f"Document {document_id} parsed successfully: {len(parsed_doc.sections)} sections, {len(all_chunks)} chunks.")

        except Exception as e:
            logger.exception(f"Failed parsing document {document_id}: {str(e)}")
            doc.status = "failed"
            doc.error_message = str(e)
            await db.commit()


ingestion_pipeline = DocumentIngestionPipeline()
