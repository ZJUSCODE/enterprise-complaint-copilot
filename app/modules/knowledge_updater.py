from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.document.parser import DocumentParser
from app.document.cleaner import DataCleaner
from app.document.chunking import ChunkingEngine

logger = logging.getLogger(__name__)


class KnowledgeUpdater:
    """Monitors knowledge base directory and auto-updates the vector store."""

    def __init__(self, vector_client: Any = None, collection_name: str = "policy_docs", embeddings: Any = None):
        self._client = vector_client
        self._collection_name = collection_name
        self._embeddings = embeddings
        self._observer = None
        self._parser = DocumentParser()
        self._cleaner = DataCleaner()
        self._chunker = ChunkingEngine(strategy="heading", max_chars=500)
        self._supported_exts = set(self._parser.supported_extensions()) | {".md"}

    def start_watching(self, kb_dir: Path) -> None:
        """Start file system watcher for the knowledge base directory."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent

            updater = self

            class KBHandler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory:
                        ext = Path(event.src_path).suffix.lower()
                        if ext in updater._supported_exts:
                            logger.info("New file detected: %s", event.src_path)
                            updater.on_file_change(Path(event.src_path))

                def on_modified(self, event):
                    if not event.is_directory:
                        ext = Path(event.src_path).suffix.lower()
                        if ext in updater._supported_exts:
                            logger.info("File modified: %s", event.src_path)
                            updater.on_file_change(Path(event.src_path))

                def on_deleted(self, event):
                    if not event.is_directory:
                        ext = Path(event.src_path).suffix.lower()
                        if ext in updater._supported_exts:
                            logger.info("File deleted: %s", event.src_path)
                            updater.on_file_delete(Path(event.src_path))

            self._observer = Observer()
            handler = KBHandler()
            self._observer.schedule(handler, str(kb_dir), recursive=False)
            self._observer.start()
            logger.info("Knowledge updater watching: %s", kb_dir)
        except ImportError:
            logger.warning("watchdog not installed, auto-update disabled")
        except Exception as exc:
            logger.warning("Failed to start watcher: %s", exc)

    def stop_watching(self) -> None:
        """Stop the file system watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def on_file_change(self, file_path: Path) -> None:
        """Handle file creation or modification."""
        if not self._client or not self._embeddings:
            logger.debug("Vector store not configured, skipping update")
            return

        try:
            chunks = self._chunk_file(file_path)
            if not chunks:
                return

            collection = self._client.get_or_create_collection(name=self._collection_name)

            # Remove old chunks for this file
            self._remove_file_chunks(collection, file_path.name)

            # Add new chunks
            texts = [c["text"] for c in chunks]
            metadatas = [c["metadata"] for c in chunks]
            ids = [c["id"] for c in chunks]
            vectors = self._embeddings.embed_documents(texts)
            collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
            logger.info("Updated %d chunks for %s", len(chunks), file_path.name)
        except Exception as exc:
            logger.warning("Failed to update %s: %s", file_path.name, exc)

    def on_file_delete(self, file_path: Path) -> None:
        """Handle file deletion."""
        if not self._client:
            return

        try:
            collection = self._client.get_or_create_collection(name=self._collection_name)
            self._remove_file_chunks(collection, file_path.name)
            logger.info("Removed chunks for deleted file: %s", file_path.name)
        except Exception as exc:
            logger.warning("Failed to remove chunks for %s: %s", file_path.name, exc)

    def _remove_file_chunks(self, collection: Any, filename: str) -> None:
        """Remove all chunks belonging to a specific file."""
        try:
            # Query for chunks from this file
            results = collection.get(where={"source_file": filename})
            if results and results.get("ids"):
                collection.delete(ids=results["ids"])
        except Exception:
            # Fallback: try to delete by ID pattern
            pass

    def _chunk_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Split file into chunks for indexing. Supports MD, PDF, Word, Excel, images."""
        ext = file_path.suffix.lower()
        name_lower = file_path.name.lower()
        category = "售后" if "after_sales" in name_lower else "物流" if "logistics" in name_lower else "生鲜" if "fresh" in name_lower else "通用"

        # Non-markdown files: use DocumentParser + cleaner + chunker
        if ext != ".md":
            try:
                sections = self._parser.parse(str(file_path))
                cleaned = self._cleaner.clean(sections)
                chunks = self._chunker.chunk(cleaned, source_file=file_path.name, source_type=ext)
                result = []
                for c in chunks:
                    citation = f"{file_path.name} > {c.metadata.section_title}" if c.metadata.section_title else file_path.name
                    result.append({
                        "id": c.metadata.chunk_id,
                        "text": c.text,
                        "metadata": {
                            "doc_id": c.metadata.chunk_id,
                            "title": c.metadata.section_title or file_path.stem,
                            "category": category,
                            "citation": citation,
                            "source_file": file_path.name,
                            "section_title": c.metadata.section_title,
                        },
                    })
                return result
            except Exception as exc:
                logger.warning("DocumentParser failed for %s: %s", file_path.name, exc)
                return []

        # Markdown files: existing heading-based splitting with cleaning
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return []
        if not content.strip():
            return []

        from app.document.parsers.base import DocumentSection

        raw_sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
        doc_sections = []
        for section in raw_sections:
            section = section.strip()
            if not section:
                continue
            heading_match = re.match(r"^##\s+(.+)$", section, re.MULTILINE)
            section_title = heading_match.group(1).strip() if heading_match else ""
            doc_sections.append(DocumentSection(
                title=section_title,
                content=section,
                section_type="heading" if section_title else "paragraph",
            ))

        cleaned = self._cleaner.clean(doc_sections)

        chunks = []
        chunk_counter = 0
        for section in cleaned:
            section_title = section.title
            citation = f"{file_path.name} > {section_title}" if section_title else file_path.name
            chunk_counter += 1
            chunks.append({
                "id": f"{file_path.stem}_chunk_{chunk_counter:03d}",
                "text": section.content,
                "metadata": {
                    "doc_id": f"{file_path.stem}_chunk_{chunk_counter:03d}",
                    "title": section_title or file_path.stem,
                    "category": category,
                    "citation": citation,
                    "source_file": file_path.name,
                    "section_title": section_title,
                },
            })

        return chunks
