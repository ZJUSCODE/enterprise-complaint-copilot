# WeKnora 集成指南（可切换外部检索后端）

> 本项目默认使用自研检索（Chroma 向量 + BM25 + RRF 融合）。
> 通过环境变量可无缝切换到 **WeKnora**（腾讯开源企业级知识框架，
> `github.com/Tencent/WeKnora`，MIT）作为外部检索底座——**检索层**升级为
> BM25 + Dense + GraphRAG + rerank 的真 hybrid，**回答生成、Guardrail、
> 评测、只读 SQL 等 Agent 能力全部保留**，零侵入。

## 架构

```
用户问题
   │
   ▼
FastAPI → 鉴权/Guardrail → Orchestrator
                                 │
                    ┌────────────┴────────────┐
                    ▼ (RETRIEVAL_BACKEND=weknora)
            WeKnora 知识库                   本地 LLM 生成
            (BM25+Dense+GraphRAG+rerank)  (回答 + 证据 + 审计)
```

## 1. 部署 WeKnora（本机 Docker）

WeKnora 最新稳定版为 `v0.7.2`，推荐用官方 docker-compose 启动：

```bash
git clone https://github.com/Tencent/WeKnora.git --branch v0.7.2
cd WeKnora
# 按官方部署手册启动（依赖 pgvector / Elasticsearch 等，占资源较大）
docker compose up -d
# 服务默认端口 8080
```

> macOS 用户需先安装 Docker Desktop。本机无 Docker 时，可先跳过本步，
> 代码层面的切换逻辑已就绪，接入时只需补环境变量。

## 2. 建知识库并导入语料

启动后通过 Web UI（`http://localhost:8080`）创建知识库，然后导入本项目语料：

```bash
# 上传本项目知识库文档（示例）
curl -X POST "http://localhost:8080/api/v1/knowledge-bases/$KB_ID/knowledge/file" \
  -H "X-API-Key: $WEKNORA_API_KEY" \
  -F "file=@knowledge_base/policies.json"
# sop/ faq/ cases/ 下的 md 同理逐个上传
```

获取 `X-API-Key`：浏览器打开 WeKnora → F12 → Network 中任选一个请求复制 `x-api-key` 头（以 `sk-` 开头）。

## 3. 配置本项目环境变量

在项目根目录 `.env`（或运行环境）中：

```bash
# 启用 WeKnora 检索后端
RETRIEVAL_BACKEND=weknora
WEKNORA_BASE_URL=http://localhost:8080
WEKNORA_API_KEY=sk-xxxxxxxx
WEKNORA_KB_ID=kb-xxxxxxxx

# 回答生成仍需 LLM（沿用现有配置）
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

不配置 `RETRIEVAL_BACKEND`（默认 `local`）时，行为与之前完全一致。

## 4. 验证

```bash
# 方式一：直接调用服务
curl -X POST "http://localhost:8080/api/v1/knowledge-search" \
  -H "X-API-Key: $WEKNORA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "生鲜坏损怎么赔付", "knowledge_base_id": "kb-xxxx"}'

# 方式二：跑项目测试（含 mock 的后端切换用例）
.venv/bin/python -m pytest tests/test_weknora_backend.py -q
```

## 5. 回退与降级

- **配置缺失**：`WEKNORA_*` 任一为空 → `weknora_backend.available=False`，
  `query()` 自动走本地 BM25/向量检索，不影响可用性。
- **WeKnora 无结果/宕机**：`search()` 返回空 → 自动回退本地检索。
- **切回本地**：删除 `RETRIEVAL_BACKEND=weknora` 即可，无需改代码。

## 6. 面试怎么讲

> "检索层我做了可插拔抽象：默认自研（Chroma + BM25 + RRF 双路融合），
> 通过环境变量可切换到腾讯开源的 WeKnora 做外部检索底座，Agent 编排、
> Guardrail、评测体系完全不动。选它是因为它在文档解析（多模态 OCR）和
> 混合检索（BM25+Dense+GraphRAG）上比我自研的轻量实现成熟，用成熟框架
> 当底座、自研保住业务控制权，是更合理的技术选型。"
