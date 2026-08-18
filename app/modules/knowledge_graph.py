from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import networkx as nx

from app.modules.base import RAGContext, RAGModule, Citation


# Rule-based triple extraction patterns for Chinese SOP documents
TRIPLE_PATTERNS = [
    # "A 导致 B" / "A 引起 B"
    (r"(.{2,10})(?:导致|引起|造成|引发)(.{2,20})", "causes"),
    # "A 需要 B" / "A 要求 B"
    (r"(.{2,10})(?:需要|要求|必须)(.{2,20})", "requires"),
    # "A 属于 B" / "A 是 B"
    (r"(.{2,10})(?:属于|是|为)(.{2,20})", "is_a"),
    # "A 包括 B"
    (r"(.{2,10})(?:包括|包含|涉及)(.{2,20})", "includes"),
    # "A 的 B" (possessive)
    (r"(.{2,10})的(.{2,10})", "has"),
    # "如果 A 则 B" / "若 A 则 B"
    (r"(?:如果|若|当)(.{2,15})(?:则|就|应|需要)(.{2,20})", "if_then"),
    # "A → B" or "A -> B"
    (r"(.{2,10})\s*[-→]>\s*(.{2,20})", "leads_to"),
]


def extract_triples(text: str) -> list[tuple[str, str, str]]:
    """Extract (subject, relation, object) triples from Chinese text using rules."""
    triples = []
    for pattern, relation in TRIPLE_PATTERNS:
        for match in re.finditer(pattern, text):
            subject = match.group(1).strip()
            obj = match.group(2).strip()
            # Clean up: remove leading/trailing punctuation
            subject = re.sub(r"^[，。、；：“”‘’（）\s]+|[，。、；：“”‘’（）\s]+$", "", subject)
            obj = re.sub(r"^[，。、；：“”‘’（）\s]+|[，。、；：“”‘’（）\s]+$", "", obj)
            if len(subject) >= 2 and len(obj) >= 2:
                triples.append((subject, relation, obj))
    return triples


class KnowledgeGraphRetriever(RAGModule):
    """Builds and queries a knowledge graph from SOP documents."""
    name = "kg_retriever"

    def __init__(self, kb_dir: Path | None = None):
        self.enabled = True
        self.graph = nx.DiGraph()
        self._doc_chunks: dict[str, str] = {}  # node_id -> source text
        if kb_dir and kb_dir.exists():
            self.build_graph(kb_dir)

    def should_activate(self, context: RAGContext) -> bool:
        return "kg" in context.retrieval_strategy

    def build_graph(self, kb_dir: Path) -> None:
        """Extract triples from markdown SOP files and build graph."""
        for md_file in sorted(kb_dir.glob("*.md")):
            if md_file.name.lower().startswith("readme"):
                continue
            content = md_file.read_text(encoding="utf-8")
            if not content.strip():
                continue

            # Split by sections
            sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
            for section in sections:
                section = section.strip()
                if not section:
                    continue

                heading_match = re.match(r"^##\s+(.+)$", section, re.MULTILINE)
                section_title = heading_match.group(1).strip() if heading_match else ""
                source = f"{md_file.name} > {section_title}" if section_title else md_file.name

                triples = extract_triples(section)
                for subj, rel, obj in triples:
                    self.graph.add_node(subj, type="entity")
                    self.graph.add_node(obj, type="entity")
                    self.graph.add_edge(subj, obj, relation=rel, source=source)
                    # Store chunk text for retrieval
                    chunk_id = f"{subj}_{rel}_{obj}"
                    self._doc_chunks[chunk_id] = section[:500]

    def _find_entities_in_query(self, query: str) -> list[str]:
        """Find graph nodes mentioned in the query."""
        entities = []
        for node in self.graph.nodes():
            if node in query:
                entities.append(node)
        return entities

    def _get_subgraph_results(self, entities: list[str], max_hops: int = 2) -> list[Citation]:
        """Traverse graph from query entities and collect relevant edges."""
        results = []
        seen = set()

        for entity in entities:
            if entity not in self.graph:
                continue
            # BFS up to max_hops
            visited = {entity}
            frontier = [(entity, 0)]
            while frontier:
                node, depth = frontier.pop(0)
                if depth >= max_hops:
                    continue
                for neighbor in self.graph.successors(node):
                    edge_data = self.graph.edges[node, neighbor]
                    edge_key = (node, edge_data.get("relation", ""), neighbor)
                    if edge_key not in seen:
                        seen.add(edge_key)
                        chunk_id = f"{node}_{edge_data.get('relation', '')}_{neighbor}"
                        excerpt = self._doc_chunks.get(chunk_id, "")
                        results.append(Citation(
                            id=chunk_id,
                            title=f"{node} → {neighbor}",
                            category="图谱",
                            citation=edge_data.get("source", "knowledge_graph"),
                            excerpt=excerpt or f"{node} {edge_data.get('relation', '')} {neighbor}",
                            retrieval_score=0.8,
                            rerank_score=0.0,
                            source="knowledge_graph",
                        ))
                    if neighbor not in visited:
                        visited.add(neighbor)
                        frontier.append((neighbor, depth + 1))
        return results

    async def execute(self, context: RAGContext) -> RAGContext:
        query = context.rewritten_query or context.query
        entities = self._find_entities_in_query(query)
        kg_results = self._get_subgraph_results(entities)
        context.kg_results = kg_results
        context.metadata["kg_retriever"] = {
            "entities_found": entities,
            "triples_retrieved": len(kg_results),
            "graph_nodes": self.graph.number_of_nodes(),
            "graph_edges": self.graph.number_of_edges(),
        }
        return context
