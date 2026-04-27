let riskChart;
let trendChart;
let activeMode = "function_call_agent";
let sessionId = localStorage.getItem("copilot_session_id") || "";
let allSampleItems = [];
let schemaCatalog = null;

const modeDescriptions = {
    function_call_agent: "Function Call Agent：适合查风险、查退款明细、查结构化业务结果。",
    sql_rag_chain: "SQL -> RAG：先查异常明细，再用售后 SOP 给出处理依据和复核判断。",
    langchain_rag: "LangChain RAG：适合查售后 SOP、赔付规则和可引用的政策依据。",
    router_demo: "Router Demo：演示系统如何先判断问题类型，再串行决定下一步工具。",
};

async function fetchJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function formatCurrency(value) {
    const number = Number(value || 0);
    if (Number.isNaN(number)) return String(value || "-");
    return `¥${number.toFixed(2)}`;
}

function formatUsd(value) {
    return `$${Number(value || 0).toFixed(6)}`;
}

function stripMarkdown(text) {
    return String(text || "")
        .replace(/\*\*(.*?)\*\*/g, "$1")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/^\s*[-*]\s+/gm, "")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
}

const highlightPattern = /(3C\s*数码|生鲜|服饰|美妆|其他|质量问题|物流延误|包装破损|仅退款|一般咨询|异常工单|赔付|退款|实付|金额|单量|订单|用户|工单|SOP|RAG|SQL|tickets|order_id|user_id|category|complaint_type|compensation_amount|pay_amount|created_at|ticket_status|is_bad_review|(?:¥|￥)?\d+(?:\.\d+)?\s*(?:元|单|条|件|次|名|个|%))/gi;

function appendHighlightedText(node, text) {
    const value = String(text ?? "");
    let lastIndex = 0;
    highlightPattern.lastIndex = 0;
    let match;
    while ((match = highlightPattern.exec(value)) !== null) {
        if (match.index > lastIndex) {
            node.appendChild(document.createTextNode(value.slice(lastIndex, match.index)));
        }
        node.appendChild(el("strong", "genui-highlight", match[0]));
        lastIndex = highlightPattern.lastIndex;
    }
    if (lastIndex < value.length) {
        node.appendChild(document.createTextNode(value.slice(lastIndex)));
    }
    return node;
}

function highlightedEl(tag, className, text) {
    const node = el(tag, className);
    appendHighlightedText(node, text);
    return node;
}

function setModeHint() {
    const labelMap = {
        function_call_agent: "当前模式：Function Call Agent",
        sql_rag_chain: "当前模式：SQL -> RAG",
        langchain_rag: "当前模式：LangChain RAG",
        router_demo: "当前模式：Router Demo",
    };
    document.getElementById("modeHint").textContent = labelMap[activeMode] || "当前模式：Copilot";
    document.getElementById("modeDescription").textContent = modeDescriptions[activeMode] || "";
}

function setStreamHint(text) {
    const node = document.getElementById("streamHint");
    if (node) node.textContent = text;
}

function renderChartFallback(selector, text) {
    const shell = document.querySelector(selector);
    if (!shell) return;
    shell.innerHTML = "";
    const fallback = el("div", "chart-fallback", text);
    shell.appendChild(fallback);
}

function renderOverview(data) {
    document.getElementById("riskRate").textContent = `${(data.risk_rate * 100).toFixed(1)}%`;
    document.getElementById("highRiskCount").textContent = data.high_risk_cnt;
    document.getElementById("totalUsers").textContent = data.total_users;
    document.getElementById("snapshotDate").textContent = data.latest_snapshot;
    document.getElementById("agentStatus").textContent = data.api_configured
        ? `${data.llm_model} / ${data.langchain_rag_enabled ? "RAG Ready" : "RAG Fallback"}`
        : "API 未配置";

    const keywordCloud = document.getElementById("keywordCloud");
    keywordCloud.innerHTML = "";
    if (!data.top_keywords.length) {
        keywordCloud.textContent = "当前样本没有可展示的高频词。";
    } else {
        data.top_keywords.forEach((item) => {
            keywordCloud.appendChild(el("span", "keyword-pill", `${item.word} · ${item.count}`));
        });
    }

    const complaintMix = document.getElementById("complaintMix");
    complaintMix.innerHTML = "";
    if (!data.complaint_mix.length) {
        complaintMix.textContent = "当前样本没有可展示的投诉结构。";
    } else {
        data.complaint_mix.forEach((item) => {
            const row = el("div", "stack-item");
            row.appendChild(el("span", "", item.label));
            row.appendChild(el("strong", "", item.value));
            complaintMix.appendChild(row);
        });
    }

    if (typeof Chart === "undefined") {
        renderChartFallback(".risk-chart-shell", `${(data.risk_rate * 100).toFixed(1)}%`);
        renderChartFallback(".trend-chart-shell", "图表库未加载，指标与明细仍可用");
        return;
    }

    const riskCtx = document.getElementById("riskChart").getContext("2d");
    if (riskChart) riskChart.destroy();
    riskChart = new Chart(riskCtx, {
        type: "doughnut",
        data: {
            labels: ["高风险用户", "其他用户"],
            datasets: [{
                data: [data.risk_rate, 1 - data.risk_rate],
                backgroundColor: ["#b85241", "#d9c7ae"],
                borderWidth: 0,
                hoverOffset: 0,
            }],
        },
        options: {
            responsive: true,
            cutout: "74%",
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const count = context.dataIndex === 0
                                ? data.high_risk_cnt
                                : Math.max(Number(data.total_users || 0) - Number(data.high_risk_cnt || 0), 0);
                            return `${context.label}: ${(Number(context.parsed || 0) * 100).toFixed(1)}% / ${count}名用户`;
                        },
                        afterLabel: (context) => context.dataIndex === 0
                            ? "原因：风险评分达到高风险阈值"
                            : "原因：未达到高风险阈值",
                    },
                },
            },
        },
    });

    const trendCtx = document.getElementById("trendChart").getContext("2d");
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(trendCtx, {
        type: "line",
        data: {
            labels: data.trend.map((item) => item.date),
            datasets: [
                {
                    label: "异常评价",
                    data: data.trend.map((item) => item.bad),
                    borderColor: "#111111",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                },
                {
                    label: "总订单量",
                    data: data.trend.map((item) => item.total),
                    borderColor: "#b7a690",
                    borderWidth: 1.6,
                    pointRadius: 0,
                    tension: 0.3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 6, color: "#8d8276" } },
                y: { grid: { color: "rgba(76,65,49,0.08)" }, ticks: { color: "#8d8276" } },
            },
            plugins: {
                legend: { labels: { color: "#544d45" } },
                tooltip: {
                    callbacks: {
                        title: (items) => `日期：${items[0]?.label || "-"}`,
                        label: (context) => {
                            const point = data.trend[context.dataIndex] || {};
                            const total = Number(point.total || 0);
                            const bad = Number(point.bad || 0);
                            const ratio = total ? ((bad / total) * 100).toFixed(1) : "0.0";
                            return `${context.dataset.label}: ${context.parsed.y}单；异常占比 ${ratio}%`;
                        },
                        afterBody: (items) => {
                            const point = data.trend[items[0]?.dataIndex] || {};
                            return Number(point.bad || 0) > 0
                                ? "原因：低分评价或客诉文本命中异常规则"
                                : "原因：当日未命中异常评价";
                        },
                    },
                },
            },
        },
    });
}

function setActiveMode(mode) {
    activeMode = mode;
    document.querySelectorAll(".mode-btn").forEach((button) => {
        button.classList.toggle("active", button.dataset.mode === mode);
    });
    setModeHint();
    renderSampleQuestions();
}

function summarizeLead(payload) {
    if (payload.mode === "guardrail" || payload.title === "高危操作已拦截") {
        return stripMarkdown(payload.summary || "当前请求已被安全策略拦截。");
    }
    if (payload.mode === "permission_denied") {
        return stripMarkdown(payload.summary || "当前角色无权使用该工作流。");
    }
    if (payload.metrics?.length) return "已生成结构化结果，可以先看关键指标和结论。";
    if (payload.table?.length) return "已命中异常明细，可以先看可视化和表格。";
    if (payload.citations?.length) return stripMarkdown(payload.summary || "已命中知识库来源，可以先看引用依据和处理建议。");
    return stripMarkdown(payload.summary || "");
}

function compactSummary(payload) {
    if (payload.metrics?.length || payload.table?.length || payload.citations?.length) {
        return "";
    }
    return stripMarkdown(payload.summary || "");
}

function renderMetrics(metrics) {
    if (!metrics || !metrics.length) return null;
    const panel = el("div", "bubble-panel");
    panel.appendChild(el("div", "citation-label", "关键指标"));
    const row = el("div", "metric-row");
    metrics.forEach((item) => {
        const pill = el("div", "metric-pill");
        pill.appendChild(highlightedEl("span", "", item.label));
        pill.appendChild(highlightedEl("strong", "", String(item.value)));
        row.appendChild(pill);
    });
    panel.appendChild(row);
    return panel;
}

function renderHighlights(items) {
    if (!items || !items.length) return null;
    const panel = el("div", "bubble-panel");
    panel.appendChild(el("div", "citation-label", "处理建议"));
    const list = el("div", "highlight-list");
    items.forEach((item) => list.appendChild(highlightedEl("div", "", stripMarkdown(item))));
    panel.appendChild(list);
    return panel;
}

function renderSql(sqlPreview) {
    if (!sqlPreview) return null;
    const panel = el("div", "sql-panel");
    panel.appendChild(el("div", "citation-label", "SQL 预览"));
    const pre = el("pre");
    pre.textContent = sqlPreview;
    panel.appendChild(pre);
    return panel;
}

function renderVisualization(rows) {
    if (!rows || !rows.length) return null;
    const panel = el("div", "viz-panel");
    panel.appendChild(el("div", "citation-label", "赔付金额可视化"));
    const list = el("div", "bar-list");
    const topRows = rows.slice(0, 5);
    const maxValue = Math.max(...topRows.map((row) => Number(row.compensation_amount || 0)), 1);

    topRows.forEach((row) => {
        const item = el("div", "bar-item");
        const tooltip = `原因：${row.reason || `${row.category || "其他"} / ${row.complaint_type || "-"} 命中异常规则`}；单量：${row.ticket_count || 1}单；占比：${Number(row.share_of_total || 0).toFixed(1)}%`;
        item.classList.add("has-row-tooltip");
        item.setAttribute("tabindex", "0");
        item.setAttribute("data-tooltip", tooltip);
        item.setAttribute("title", tooltip);
        const head = el("div", "bar-head");
        head.appendChild(highlightedEl("span", "", `${row.category || "其他"} / ${row.complaint_type || "-"}`));
        head.appendChild(highlightedEl("strong", "", formatCurrency(row.compensation_amount)));
        const track = el("div", "bar-track");
        const fill = el("div", "bar-fill");
        fill.style.width = `${Math.max((Number(row.compensation_amount || 0) / maxValue) * 100, 8)}%`;
        track.appendChild(fill);
        item.appendChild(head);
        item.appendChild(track);
        item.appendChild(highlightedEl("div", "bar-meta", `单量 ${row.ticket_count || 1}单 · 占比 ${Number(row.share_of_total || 0).toFixed(1)}%`));
        list.appendChild(item);
    });

    panel.appendChild(list);
    return panel;
}

function renderTable(rows) {
    if (!rows || !rows.length) return null;
    const panel = el("div", "bubble-panel");
    panel.appendChild(el("div", "citation-label", "异常明细"));
    const grid = el("div", "table-grid");
    rows.forEach((row) => {
        const card = el("div", "table-card");
        const header = el("div", "table-row");
        [
            ["订单", row.order_id],
            ["用户", row.user_id],
            ["日期", row.created_at],
        ].forEach(([label, value]) => {
            const item = el("div");
            item.appendChild(el("span", "table-label", label));
            item.appendChild(highlightedEl("div", "table-value", value || "-"));
            header.appendChild(item);
        });
        card.appendChild(header);

        const body = el("div", "table-row");
        [
            ["类目", row.category],
            ["投诉类型", row.complaint_type],
            ["赔付金额", formatCurrency(row.compensation_amount)],
        ].forEach(([label, value]) => {
            const item = el("div");
            item.appendChild(el("span", "table-label", label));
            item.appendChild(highlightedEl("div", "table-value", String(value || "-")));
            body.appendChild(item);
        });
        card.appendChild(body);

        const footer = el("div");
        footer.style.marginTop = "10px";
        footer.appendChild(el("span", "table-label", "评论摘要"));
        footer.appendChild(highlightedEl("div", "table-value", row.comment || "-"));
        card.appendChild(footer);
        grid.appendChild(card);
    });
    panel.appendChild(grid);
    return panel;
}

function renderCitations(items) {
    if (!items || !items.length) return null;
    const panel = el("div", "citation-panel");
    panel.appendChild(el("div", "citation-label", "引用来源"));
    items.forEach((item) => {
        const line = el("p");
        const scoreBits = [];
        if (item.source) scoreBits.push(item.source);
        if (item.retrieval_score !== undefined) scoreBits.push(`retrieval ${item.retrieval_score}`);
        if (item.rerank_score !== undefined) scoreBits.push(`rerank ${item.rerank_score}`);
        appendHighlightedText(line, scoreBits.length
            ? `${item.label}：${item.text} (${scoreBits.join(" · ")})`
            : `${item.label}：${item.text}`);
        panel.appendChild(line);
    });
    return panel;
}

function renderReviewCase(item) {
    if (!item) return null;
    const panel = el("div", "bubble-panel review-panel");
    panel.appendChild(el("div", "citation-label", "人工复核队列"));
    const row = el("div", "review-case");
    row.appendChild(el("strong", "", item.case_id || "-"));
    row.appendChild(el("span", "", item.status || "pending"));
    panel.appendChild(row);
    panel.appendChild(highlightedEl("p", "", item.reason || "需要人工复核"));
    return panel;
}

function summarizeTrace(item) {
    if (!item) return "";
    if (item.tool === "query_refund_cases") {
        return "已完成异常退款明细查询，并返回指标、明细和 SQL 预览。";
    }
    if (item.tool === "search_policy_docs") {
        return "已完成售后政策检索，并返回相关引用来源。";
    }
    if (item.tool === "get_user_risk") {
        return "已完成用户风险评分查询，并返回风险等级和建议动作。";
    }
    if (item.tool === "langchain_rag") {
        return "已完成 LangChain / ChromaDB RAG 检索，并返回政策依据。";
    }
    return stripMarkdown(item.result_summary || "");
}

function renderToolTrace(items) {
    if (!items || !items.length) return null;
    const panel = el("div", "bubble-panel");
    panel.appendChild(el("div", "citation-label", "执行轨迹"));
    const grid = el("div", "trace-grid");
    items.forEach((item) => {
        const trace = el("div", "trace-item");
        trace.appendChild(el("div", "trace-name", item.tool));
        trace.appendChild(highlightedEl("div", "trace-detail", summarizeTrace(item)));
        grid.appendChild(trace);
    });
    panel.appendChild(grid);
    return panel;
}

function renderRuntimeMeta(payload) {
    if (!payload?.token_usage && payload?.estimated_cost_usd === undefined && payload?.retry_count === undefined) return null;
    const panel = el("div", "runtime-meta");
    const usage = payload.token_usage || {};
    if (payload.token_usage) {
        const parts = [
            `total ${usage.total_tokens || 0}`,
            `prompt ${usage.prompt_tokens || 0}`,
            `completion ${usage.completion_tokens || 0}`,
        ];
        if (usage.embedding_tokens !== undefined) {
            parts.splice(1, 0, `embedding ${usage.embedding_tokens || 0}`);
        }
        panel.appendChild(el("span", "", `tokens ${parts.join(" / ")}`));
    }
    if (payload.cost_breakdown) {
        panel.appendChild(el("span", "", `embedding ${formatUsd(payload.cost_breakdown.embedding_cost_usd)} · prompt ${formatUsd(payload.cost_breakdown.prompt_cost_usd)} · completion ${formatUsd(payload.cost_breakdown.completion_cost_usd)}`));
    } else if (payload.estimated_cost_usd !== undefined) {
        panel.appendChild(el("span", "", `cost ${formatUsd(payload.estimated_cost_usd)}`));
    }
    if (payload.retry_count !== undefined) {
        panel.appendChild(el("span", "", `retry ${payload.retry_count}`));
    }
    return panel;
}

async function submitFeedback(requestId, rating, comment, panel) {
    const status = panel.querySelector(".feedback-status");
    const buttons = panel.querySelectorAll("button");
    buttons.forEach((button) => { button.disabled = true; });
    if (status) status.textContent = "记录中...";
    try {
        await fetchJson("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                request_id: requestId,
                session_id: sessionId || null,
                rating,
                comment: comment || null,
            }),
        });
        panel.classList.add("feedback-submitted");
        if (status) status.textContent = rating === "up" ? "已记录：有帮助" : "已记录：需要改进";
    } catch (error) {
        buttons.forEach((button) => { button.disabled = false; });
        if (status) status.textContent = `反馈失败：${error.message}`;
    }
}

function renderFeedback(payload) {
    if (!payload?.request_id) return null;
    const panel = el("div", "feedback-panel");
    panel.appendChild(el("span", "citation-label", "回答反馈"));
    const controls = el("div", "feedback-controls");
    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 500;
    input.placeholder = "可选：补充原因";
    input.className = "feedback-comment";
    const up = el("button", "feedback-btn", "赞");
    const down = el("button", "feedback-btn", "踩");
    up.type = "button";
    down.type = "button";
    controls.appendChild(up);
    controls.appendChild(down);
    controls.appendChild(input);
    panel.appendChild(controls);
    panel.appendChild(el("div", "feedback-status", `request_id: ${payload.request_id}`));
    up.addEventListener("click", () => submitFeedback(payload.request_id, "up", input.value.trim(), panel));
    down.addEventListener("click", () => submitFeedback(payload.request_id, "down", input.value.trim(), panel));
    return panel;
}

function renderSummary(payload) {
    const container = el("div", "bubble-summary");
    const lead = stripMarkdown(summarizeLead(payload));
    if (lead) {
        container.appendChild(highlightedEl("span", "summary-lead", lead));
    }

    const compact = compactSummary(payload);
    if (compact && compact !== lead) {
        container.appendChild(highlightedEl("p", "", compact));
    }
    return container;
}

function addMessage(role, payload) {
    const conversation = document.getElementById("conversation");
    if (role === "user") {
        conversation.classList.add("has-results");
    }
    const wrapper = el("div", `message ${role}`);
    const bubble = el("div", "bubble");
    wrapper.appendChild(bubble);
    conversation.appendChild(wrapper);

    if (role === "user") {
        bubble.textContent = payload;
    } else {
        bubble.appendChild(el("p", "bubble-title", payload.title || "Copilot"));
        bubble.appendChild(renderSummary(payload));
        const panels = el("div", "bubble-panels");
        [
            renderMetrics(payload.metrics),
            renderVisualization(payload.table),
            renderHighlights(payload.highlights),
            renderSql(payload.sql_preview),
            renderTable(payload.table),
            renderCitations(payload.citations),
            renderReviewCase(payload.review_case),
            renderToolTrace(payload.tool_trace),
            renderRuntimeMeta(payload),
        ].filter(Boolean).forEach((panel) => panels.appendChild(panel));
        if (panels.children.length) bubble.appendChild(panels);
        const feedback = renderFeedback(payload);
        if (feedback) bubble.appendChild(feedback);
    }

    conversation.scrollTop = conversation.scrollHeight;
    return wrapper;
}

function addLoadingMessage() {
    const conversation = document.getElementById("conversation");
    const wrapper = el("div", "message assistant loading-bubble");
    wrapper.setAttribute("data-loading", "true");
    const bubble = el("div", "bubble");
    bubble.appendChild(el("p", "bubble-title", "正在处理"));
    bubble.appendChild(el("div", "loading-line", "正在进行意图识别、工具选择和检索准备，请稍候。"));
    wrapper.appendChild(bubble);
    conversation.appendChild(wrapper);
    conversation.scrollTop = conversation.scrollHeight;
    return wrapper;
}

function updateLoadingMessage(wrapper, text) {
    const target = wrapper?.querySelector(".loading-line");
    if (target) target.textContent = text;
}

function splitSseEvents(buffer) {
    const parts = buffer.split("\n\n");
    return {
        complete: parts.slice(0, -1),
        remainder: parts[parts.length - 1] || "",
    };
}

async function readStreamedChat(message, loading) {
    const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, mode: activeMode, session_id: sessionId || null }),
    });
    if (!response.ok || !response.body) throw new Error(`Stream failed: ${response.status}`);

    setStreamHint("流式状态已连接");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalPayload = null;

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { complete, remainder } = splitSseEvents(buffer);
        buffer = remainder;

        for (const chunk of complete) {
            const lines = chunk.split("\n").filter(Boolean);
            const eventLine = lines.find((line) => line.startsWith("event:"));
            const dataLine = lines.find((line) => line.startsWith("data:"));
            if (!eventLine || !dataLine) continue;
            const eventName = eventLine.replace("event:", "").trim();
            const data = JSON.parse(dataLine.replace("data:", "").trim());
            if (eventName === "status") {
                updateLoadingMessage(loading, data.message);
            } else if (eventName === "final") {
                finalPayload = data;
            } else if (eventName === "error") {
                throw new Error(data.message);
            }
        }
    }
    return finalPayload;
}

async function readFallbackChat(message) {
    setStreamHint("当前为普通响应模式");
    return fetchJson("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, mode: activeMode, session_id: sessionId || null }),
    });
}

async function submitMessage(message) {
    addMessage("user", message);
    const loading = addLoadingMessage();
    try {
        let payload;
        try {
            payload = await readStreamedChat(message, loading);
        } catch (streamError) {
            updateLoadingMessage(loading, "正在整理结果，请稍候。");
            payload = await readFallbackChat(message);
        }
        if (payload?.session_id) {
            sessionId = payload.session_id;
            localStorage.setItem("copilot_session_id", sessionId);
        }
        loading.remove();
        addMessage("assistant", payload);
    } catch (error) {
        loading.remove();
        addMessage("assistant", {
            title: "请求失败",
            summary: "本次调用没有成功返回结果，请检查后端服务或 API 配置。",
            highlights: [String(error)],
        });
    }
}

async function loadSamples() {
    const data = await fetchJson("/api/sample-questions");
    allSampleItems = data.items || [];
    renderSampleQuestions();
}

function renderSampleQuestions() {
    const root = document.getElementById("sampleQuestions");
    if (!root) return;
    root.innerHTML = "";
    const preferred = allSampleItems.filter((item) => item.mode === activeMode);
    const fallback = allSampleItems.filter((item) => item.mode !== activeMode);
    const items = [...preferred, ...fallback].slice(0, 4);
    items.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = item.text;
        button.addEventListener("click", () => {
            setActiveMode(item.mode);
            document.getElementById("chatInput").value = item.text;
            document.getElementById("chatInput").focus();
        });
        root.appendChild(button);
    });
}

function bindHeroActions() {
    document.querySelectorAll("[data-fill]").forEach((button) => {
        button.addEventListener("click", async () => {
            const mode = button.dataset.mode || activeMode;
            const text = button.dataset.fill || "";
            setActiveMode(mode);
            document.getElementById("chatInput").value = text;
            document.getElementById("chatInput").focus();
            if (button.dataset.run === "true" && text.trim()) {
                document.getElementById("chatInput").value = "";
                await submitMessage(text.trim());
            }
        });
    });
}

function renderSchema(catalog) {
    const root = document.getElementById("schemaExplorer");
    if (!root) return;
    schemaCatalog = catalog;
    const table = catalog.tables?.[0] || {};
    const columns = table.columns || [];
    root.innerHTML = "";
    root.appendChild(highlightedEl("p", "schema-desc", `${table.name || "tickets"}：${table.description || ""}`));

    const metricList = el("div", "schema-metrics");
    (catalog.metrics || []).forEach((metric) => {
        const chip = el("span", "schema-chip");
        appendHighlightedText(chip, `${metric.name} = ${metric.expression}`);
        metricList.appendChild(chip);
    });
    root.appendChild(metricList);

    const list = el("div", "schema-list");
    columns.forEach((column) => {
        const item = el("div", "schema-field");
        const head = el("div", "schema-field-head");
        head.appendChild(highlightedEl("strong", "", column.name));
        head.appendChild(el("span", "", column.type));
        item.appendChild(head);
        item.appendChild(highlightedEl("p", "", column.description));
        const tags = el("div", "schema-tags");
        if (column.filterable) tags.appendChild(el("span", "", "可筛选"));
        if (column.dimension) tags.appendChild(el("span", "", "维度"));
        item.appendChild(tags);
        list.appendChild(item);
    });
    root.appendChild(list);

    const safety = el("p", "schema-safety");
    appendHighlightedText(safety, `安全：${catalog.safety?.validator || "validate_readonly_sql"} 只允许 ${catalog.safety?.allowed_statements?.join(" / ") || "SELECT"}。`);
    root.appendChild(safety);
}

async function loadSchema() {
    try {
        renderSchema(await fetchJson("/api/schema"));
    } catch (error) {
        const root = document.getElementById("schemaExplorer");
        if (root) root.textContent = `Schema 加载失败：${error.message}`;
    }
}

function renderDailyReport(report) {
    const root = document.getElementById("dailyReport");
    if (!root) return;
    root.innerHTML = "";
    root.appendChild(highlightedEl("p", "daily-headline", report.headline || "暂无异常播报。"));

    const metricRow = el("div", "daily-metrics");
    (report.metrics || []).forEach((metric) => {
        const item = el("div", "daily-metric");
        item.appendChild(el("span", "", metric.label));
        item.appendChild(highlightedEl("strong", "", String(metric.value)));
        metricRow.appendChild(item);
    });
    root.appendChild(metricRow);

    const risks = el("div", "daily-risk-list");
    (report.top_risks || []).slice(0, 3).forEach((risk) => {
        const item = el("div", "daily-risk-item");
        item.appendChild(highlightedEl("strong", "", `${risk.category} / ${risk.complaint_type}`));
        item.appendChild(highlightedEl("span", "", `${risk.order_count}单 · 赔付 ${formatCurrency(risk.compensation_total)} · 占比 ${risk.share}%`));
        risks.appendChild(item);
    });
    if (!risks.children.length) {
        risks.appendChild(el("div", "daily-risk-item", "当日未命中异常风险。"));
    }
    root.appendChild(risks);

    const actions = el("div", "daily-actions");
    (report.recommended_actions || []).forEach((action) => actions.appendChild(highlightedEl("div", "", action)));
    root.appendChild(actions);
    root.appendChild(el("div", "daily-mock-note", report.delivery_mock?.note || "当前为 mock 播报，不调用真实 webhook。"));
}

async function loadDailyReport() {
    try {
        renderDailyReport(await fetchJson("/api/reports/daily-risk"));
    } catch (error) {
        const root = document.getElementById("dailyReport");
        if (root) root.textContent = `日报加载失败：${error.message}`;
    }
}

async function bootstrap() {
    renderOverview(await fetchJson("/api/overview"));
    await loadSchema();
    await loadDailyReport();
    await loadSamples();
    bindHeroActions();

    document.querySelectorAll(".mode-btn").forEach((button) => {
        button.addEventListener("click", () => setActiveMode(button.dataset.mode));
    });
    setActiveMode(activeMode);

    const form = document.getElementById("chatForm");
    const input = document.getElementById("chatInput");

    input.addEventListener("keydown", async (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            const message = input.value.trim();
            if (!message) return;
            input.value = "";
            await submitMessage(message);
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message) return;
        input.value = "";
        await submitMessage(message);
    });
}

window.addEventListener("DOMContentLoaded", () => {
    bootstrap().catch((error) => {
        console.error(error);
        addMessage("assistant", {
            title: "初始化失败",
            summary: "页面已加载，但概览数据初始化未完成。",
            highlights: [String(error)],
        });
    });
});
