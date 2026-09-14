import os
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from config.settings import settings


class ChromaVectorStore:
    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or str(settings.CHROMA_PERSIST_DIR.resolve())
        os.makedirs(self.persist_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True)
        )
        self.docs_collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        self.patterns_collection = self.client.get_or_create_collection(
            name="patterns",
            metadata={"hnsw:space": "cosine"}
        )

    def upsert_document_chunks(
        self,
        project_id: str,
        document_id: str,
        chunks: List[Dict[str, Any]]
    ) -> None:
        if not chunks:
            return

        ids = [f"{document_id}_{c['section_id']}_{c['chunk_index']}" for c in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [{
            "project_id": str(project_id),
            "document_id": str(document_id),
            "section_id": str(c.get("section_id", "")),
            "section_title": str(c.get("title", "")),
            "page": int(c.get("page_number") or 1),
            "kind": str(c.get("kind", "PRD"))
        } for c in chunks]

        self.docs_collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

    def query_documents(
        self,
        project_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        total_docs = self.docs_collection.count()
        if total_docs == 0:
            return []
        
        limit = min(top_k, total_docs)
        results = self.docs_collection.query(
            query_texts=[query],
            n_results=limit,
            where={"project_id": str(project_id)}
        )
        
        output = []
        if results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            distances = results.get("distances", [[]])[0]
            ids = results["ids"][0]
            for i in range(len(docs)):
                dist = distances[i] if (distances and i < len(distances)) else 0.5
                similarity = max(0.0, min(1.0, 1.0 - (dist / 2.0)))
                output.append({
                    "id": ids[i],
                    "content": docs[i],
                    "metadata": metas[i],
                    "similarity_score": round(similarity, 4),
                    "distance": dist
                })
        return output

    def upsert_pattern(
        self,
        pattern_id: str,
        name: str,
        intent: str,
        structure: str,
        when_to_use: str,
        when_not_to_use: str = "",
        tags: Optional[List[str]] = None
    ) -> None:
        tags_list = tags or []
        tags_str = ",".join(tags_list)
        embedding_text = "\n".join([
            f"Pattern: {name}",
            f"Intent: {intent}",
            f"When to Use: {when_to_use}",
            f"Structure: {structure}",
            f"When Not to Use: {when_not_to_use}",
            f"Tags: {tags_str}"
        ])

        metadata = {
            "pattern_id": pattern_id,
            "name": name,
            "tags": tags_str,
            "source": "Pattern_KB"
        }

        self.patterns_collection.upsert(
            ids=[pattern_id],
            documents=[embedding_text],
            metadatas=[metadata]
        )

    def delete_pattern(self, pattern_id: str) -> None:
        try:
            self.patterns_collection.delete(ids=[pattern_id])
        except Exception:
            pass

    def query_patterns(
        self,
        query: str,
        top_k: int = 8,
        tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        total_patterns = self.patterns_collection.count()
        if total_patterns == 0:
            return []

        limit = min(total_patterns, max(top_k * 4, 10))
        results = self.patterns_collection.query(
            query_texts=[query],
            n_results=limit
        )

        output = []
        if results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            distances = results.get("distances", [[]])[0]
            ids = results["ids"][0]

            for i in range(len(docs)):
                meta = metas[i] if i < len(metas) else {}
                pattern_tags = [t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()]

                # Tag filter (Match Any / OR semantics)
                if tags:
                    requested_tags = [t.strip().lower() for t in tags if t.strip()]
                    has_match = any(rt in pattern_tags for rt in requested_tags)
                    if not has_match:
                        continue

                dist = distances[i] if (distances and i < len(distances)) else 0.5
                similarity = max(0.0, min(1.0, 1.0 - (dist / 2.0)))

                output.append({
                    "id": ids[i],
                    "name": meta.get("name", ""),
                    "content": docs[i],
                    "metadata": meta,
                    "similarity_score": round(similarity, 4)
                })

                if len(output) >= top_k:
                    break

        return output

    def delete_document(self, project_id: str, document_id: str) -> None:
        self.docs_collection.delete(
            where={"$and": [{"project_id": str(project_id)}, {"document_id": str(document_id)}]}
        )


vector_store = ChromaVectorStore()
