export function formatPercent(value: number | undefined, digits = 1) {
  const normalized = Number(value || 0) * 100;
  return `${normalized.toFixed(digits)}%`;
}

export function formatNumber(value: string | number | undefined) {
  const normalized = Number(value);
  if (Number.isNaN(normalized)) return value === undefined ? '-' : String(value);
  return normalized.toLocaleString('zh-CN');
}

export function formatMoney(value: string | number | undefined) {
  const normalized = Number(value || 0);
  if (Number.isNaN(normalized)) return String(value || '-');
  return `¥${normalized.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function workflowLabel(mode: string) {
  const labels: Record<string, string> = {
    function_call_agent: '数据查询',
    sql_rag_chain: 'SQL + SOP',
    langchain_rag: '政策问答',
    router_demo: '自动路由',
    auto: '自动判断',
  };
  return labels[mode] || mode;
}

export function reviewStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: '待复核',
    resolved: '已通过',
    rejected: '已驳回',
  };
  return labels[status] || status;
}
