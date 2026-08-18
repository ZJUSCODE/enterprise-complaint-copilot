from __future__ import annotations

import time
from typing import Any

from app.modules.base import RAGContext, RAGModule


class ModularRAGPipeline:
    """Orchestrates pluggable RAG modules in sequence."""

    def __init__(self, modules: list[RAGModule] | None = None):
        self.modules: list[RAGModule] = modules or []

    def add_module(self, module: RAGModule) -> None:
        self.modules.append(module)

    async def run(self, query: str, initial_metadata: dict[str, Any] | None = None) -> RAGContext:
        ctx = RAGContext(query=query)
        if initial_metadata:
            ctx.metadata.update(initial_metadata)
        for module in self.modules:
            if not module.enabled or not module.should_activate(ctx):
                ctx.metadata.setdefault("skipped_modules", []).append(module.name)
                continue
            ctx.metadata.setdefault("activated_modules", []).append(module.name)
            start = time.perf_counter()
            ctx = await module.execute(ctx)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            ctx.metadata.setdefault("module_timings", {})[module.name] = elapsed_ms
        return ctx
