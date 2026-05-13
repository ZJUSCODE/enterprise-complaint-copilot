# Enterprise Document Processing System Design

**Date:** 2026-05-13
**Status:** Confirmed
**Scope:** Upgrade from Markdown-only RAG to enterprise-grade document processing with real file parsing, data cleaning, version management, lineage tracking, and audit logging.

---

## 1. Problem Statement

Current system only loads pre-processed Markdown files. To reach true enterprise-grade quality, we need:

1. **Document Parsing** — Support PDF, Word (.docx), Excel (.xlsx), OCR (images/scanned docs)
2. **Data Cleaning** — Enterprise-level deduplication, noise removal, conflict detection, quality scoring
3. **Version Management** — Git-level versioning with branches, diff, rollback, merge
4. **Lineage Tracking** — Chunk-level tracking of processing step history
5. **Audit Logging** — Full operation audit for document, query, system, and sensitive operations
6. **Public Datasets** — Real-world documents for demo purposes

---

## 2. DocumentParser Layer

### Architecture

```
app/document/
├── __init__.py
├── parser.py              # DocumentParser facade + factory
├── parsers/
│   ├── __init__.py
│   ├── base.py            # BaseParser ABC
│   ├── pdf_parser.py      # PyMuPDF (fitz)
│   ├── word_parser.py     # python-docx
│   ├── excel_parser.py    # openpyxl
│   └── ocr_parser.py      # PaddleOCR
```

### BaseParser ABC

```python
class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> list[DocumentSection]:
        """Parse file into structured sections."""
        ...

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        ...
```

### DocumentSection Data Model

```python
@dataclass
class DocumentSection:
    title: str
    content: str
    section_type: str        # heading / paragraph / table / image / code
    page_number: int | None
    metadata: dict[str, Any] # font info, position, table structure, etc.
    raw_bytes: bytes | None  # for images
    confidence: float = 1.0  # OCR confidence
```

### Parser Details

| Parser | Library | Key Capabilities |
|--------|---------|-----------------|
| PDF | PyMuPDF (fitz) | Text extraction, table detection, image extraction, metadata |
| Word | python-docx | Heading hierarchy, tables, images, styles |
| Excel | openpyxl | Sheet iteration, merged cells, formulas, charts data |
| OCR | PaddleOCR | Image text recognition, scanned PDF support, multi-language |

### DocumentParser Facade

```python
class DocumentParser:
    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}
        self._register_defaults()

    def parse(self, file_path: str) -> list[DocumentSection]:
        ext = Path(file_path).suffix.lower()
        parser = self._parsers.get(ext)
        if not parser:
            raise ValueError(f"Unsupported file type: {ext}")
        return parser.parse(file_path)

    def register(self, ext: str, parser: BaseParser) -> None:
        self._parsers[ext] = parser
```

---

## 3. DataCleaner Layer

### Architecture

```
app/document/
├── cleaner.py             # DataCleaner pipeline
```

### Cleaning Pipeline Steps

1. **Deduplication** — Content hash + semantic similarity (cosine > 0.95 → duplicate)
2. **Noise Removal** — Headers/footers, page numbers, watermarks, boilerplate text
3. **Table Extraction** — Structured table → natural language conversion for embedding
4. **Conflict Detection** — Flag contradictory information across documents
5. **Quality Scoring** — Score each chunk (completeness, readability, information density)

### Quality Score Model

```python
@dataclass
class QualityScore:
    completeness: float     # 0-1
    readability: float      # 0-1
    information_density: float  # 0-1
    overall: float          # weighted average
    issues: list[str]       # detected problems
```

### Conflict Detection

```python
@dataclass
class ConflictRecord:
    chunk_a_id: str
    chunk_b_id: str
    conflict_type: str      # contradiction / outdated / ambiguous
    description: str
    severity: str           # low / medium / high
```

---

## 4. VersionManager

### Architecture

```
app/document/
├── version.py             # VersionManager
```

### Design

Git-level version management operating on the knowledge base:

- **Branches** — `main`, `staging`, `experiment/*`
- **Snapshots** — Full KB state at a point in time
- **Diff** — Compare two versions (added/removed/modified chunks)
- **Rollback** — Revert to any previous version
- **Merge** — Merge branches with conflict resolution

### Version Record

```python
@dataclass
class VersionRecord:
    version_id: str
    branch: str
    parent_id: str | None
    timestamp: datetime
    message: str
    author: str
    chunk_count: int
    added: int
    removed: int
    modified: int
    snapshot_path: str      # path to KB snapshot
```

### Storage

- Metadata: SQLite table `kb_versions`
- Snapshots: `data/versions/{version_id}/` directory containing ChromaDB export

---

## 5. LineageTracker

### Architecture

```
app/document/
├── lineage.py             # LineageTracker
```

### Design

Chunk-level tracking of the entire processing pipeline:

```python
@dataclass
class LineageRecord:
    chunk_id: str
    source_file: str
    source_page: int | None
    source_section: str
    processing_steps: list[ProcessingStep]
    created_at: datetime
    updated_at: datetime
    version_id: str

@dataclass
class ProcessingStep:
    step_name: str          # parse / clean / chunk / embed / index
    timestamp: datetime
    input_hash: str
    output_hash: str
    parameters: dict[str, Any]
    duration_ms: float
```

### Query Interface

- `get_lineage(chunk_id)` → full processing history
- `get_chunks_from_file(file_path)` → all chunks from a source file
- `get_chunks_by_step(step_name)` → all chunks processed by a specific step
- `trace_back(chunk_id, step_name)` → state at a specific processing step

---

## 6. AuditLogger

### Architecture

```
app/document/
├── audit.py               # AuditLogger
```

### Event Categories

| Category | Examples |
|----------|---------|
| **Document** | upload, delete, update, parse, version_create, version_rollback |
| **Query** | search, retrieve, generate_answer, feedback |
| **System** | index_rebuild, model_change, config_update, cleanup |
| **Sensitive** | permission_check, data_export, bulk_operation |

### Audit Event

```python
@dataclass
class AuditEvent:
    event_id: str
    timestamp: datetime
    category: str           # document / query / system / sensitive
    action: str
    actor: str              # user_id or "system"
    target: str             # file path, chunk id, etc.
    details: dict[str, Any]
    ip_address: str | None
    session_id: str | None
    result: str             # success / failure / blocked
```

### Storage

- Primary: SQLite table `audit_log`
- Retention: Configurable (default 90 days)
- Query: Filter by category, action, actor, time range

---

## 7. ChunkingEngine

### Architecture

```
app/document/
├── chunking.py            # ChunkingEngine with multiple strategies
```

### Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| **Fixed** | Character/token-based fixed size | Simple baseline |
| **Recursive** | LangChain RecursiveCharacterTextSplitter | General purpose |
| **Semantic** | Embedding-based boundary detection | High-quality retrieval |
| **Heading** | Section-based splitting from parsed structure | Well-structured docs |
| **Small-to-Top** | Small chunks for matching, parent context for generation | Current system's approach |

### Chunk Metadata

```python
@dataclass
class ChunkMetadata:
    chunk_id: str
    source_file: str
    source_type: str        # pdf / docx / xlsx / image / md
    page_number: int | None
    section_title: str
    heading_hierarchy: list[str]
    char_count: int
    token_count: int
    quality_score: float
    lineage_id: str
```

---

## 8. Public Datasets

### Dataset Sources

| Type | Source | Format | Size |
|------|--------|--------|------|
| Company Reports | Annual reports, financial statements | PDF | ~20 docs |
| Technical Documentation | API docs, architecture specs | Markdown/Word | ~30 docs |
| Academic Papers | RAG/NLP research papers | PDF | ~15 docs |
| Policy Documents | Customer service policies, SOPs | Word/PDF | ~20 docs |
| Structured Data | Product catalogs, pricing tables | Excel | ~10 files |

### Storage

```
data/datasets/
├── reports/           # Company reports (PDF)
├── technical/         # Technical docs (MD/DOCX)
├── papers/            # Academic papers (PDF)
├── policies/          # Policy documents (Word/PDF)
└── structured/        # Excel data files
```

---

## 9. Integration Plan

### 9.1 Replace `_load_and_chunk_markdown_docs`

Current flow:
```python
def _load_and_chunk_markdown_docs(self) -> list:
    # Only loads .md files from data/knowledge_base/
```

New flow:
```python
def _load_and_process_documents(self) -> list:
    parser = DocumentParser()
    cleaner = DataCleaner()
    chunker = ChunkingEngine()
    lineage = LineageTracker()

    all_chunks = []
    for file_path in self._discover_files():
        # 1. Parse
        sections = parser.parse(file_path)
        # 2. Clean
        cleaned = cleaner.clean(sections)
        # 3. Chunk
        chunks = chunker.chunk(cleaned)
        # 4. Track lineage
        for chunk in chunks:
            lineage.record(chunk, file_path)
        all_chunks.extend(chunks)

    return all_chunks
```

### 9.2 New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents` | GET | List all documents in KB |
| `/api/documents` | POST | Upload new document |
| `/api/documents/{id}` | DELETE | Remove document |
| `/api/documents/{id}/lineage` | GET | Get chunk lineage for document |
| `/api/versions` | GET | List KB versions |
| `/api/versions` | POST | Create new version snapshot |
| `/api/versions/{id}/rollback` | POST | Rollback to version |
| `/api/audit` | GET | Query audit log |
| `/api/audit/stats` | GET | Audit statistics |

### 9.3 Frontend Additions

- **Document Manager** — Upload, list, delete documents with metadata
- **Lineage Viewer** — Visualize chunk processing history
- **Version Timeline** — Browse and rollback KB versions
- **Audit Dashboard** — Search and filter audit events

### 9.4 Dependencies

```txt
PyMuPDF>=1.24
python-docx>=1.1
openpyxl>=3.1
paddleocr>=2.7
paddlepaddle>=2.6
```

---

## 10. File Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `app/document/__init__.py` | Package init |
| `app/document/parser.py` | DocumentParser facade |
| `app/document/parsers/__init__.py` | Parsers package |
| `app/document/parsers/base.py` | BaseParser ABC |
| `app/document/parsers/pdf_parser.py` | PDF parser |
| `app/document/parsers/word_parser.py` | Word parser |
| `app/document/parsers/excel_parser.py` | Excel parser |
| `app/document/parsers/ocr_parser.py` | OCR parser |
| `app/document/cleaner.py` | DataCleaner |
| `app/document/version.py` | VersionManager |
| `app/document/lineage.py` | LineageTracker |
| `app/document/audit.py` | AuditLogger |
| `app/document/chunking.py` | ChunkingEngine |

### Modified Files

| File | Changes |
|------|---------|
| `app/rag.py` | Replace `_load_and_chunk_markdown_docs` with new pipeline |
| `app/runtime.py` | Add document management, version, audit API endpoints |
| `requirements.txt` | Add PyMuPDF, python-docx, openpyxl, paddleocr, paddlepaddle |
| `frontend/src/types/api.ts` | Add document, version, audit, lineage types |
| `frontend/src/api/client.ts` | Add API client functions |
| `frontend/src/views/CopilotView.vue` | Add document manager panel |

### Test Files

| File | Tests |
|------|-------|
| `tests/test_document_parser.py` | Parser facade + individual parsers |
| `tests/test_data_cleaner.py` | Cleaning pipeline |
| `tests/test_version_manager.py` | Version operations |
| `tests/test_lineage_tracker.py` | Lineage recording and query |
| `tests/test_audit_logger.py` | Audit event logging |
| `tests/test_chunking_engine.py` | Chunking strategies |

---

## 11. Success Criteria

1. All 4 file formats (PDF, Word, Excel, Image) parse correctly
2. Cleaning pipeline removes noise and detects duplicates
3. Version manager can create, diff, and rollback snapshots
4. Every chunk has complete lineage from source to index
5. All operations are audit-logged with category and actor
6. Public datasets load and index without errors
7. All new tests pass (estimated 40+ new tests)
8. Frontend can upload documents and view lineage
