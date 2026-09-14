from abc import ABC, abstractmethod
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel, Field


class ParsedSection(BaseModel):
    section_id: str
    title: str
    level: int = 1
    page_number: Optional[int] = None
    content: str


class ParsedDocument(BaseModel):
    filename: str
    doc_type: str
    sections: List[ParsedSection] = Field(default_factory=list)
    raw_text: str = ""


class BaseDocumentParser(ABC):
    @abstractmethod
    def parse(self, file_path: Path) -> ParsedDocument:
        pass
