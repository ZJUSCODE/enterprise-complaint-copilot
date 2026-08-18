export type ChatMode = 'function_call_agent' | 'sql_rag_chain' | 'langchain_rag' | 'router_demo' | 'auto' | 'multi_agent' | 'modular_rag';
export type Role = 'viewer' | 'analyst' | 'supervisor';
export type ReviewStatus = 'pending' | 'resolved' | 'rejected';
export type ResponseLanguage = 'auto' | 'zh' | 'en';

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  role: Role;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: AuthUser;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
}

export interface TrendPoint {
  date: string;
  bad: number;
  total: number;
}

export interface CountItem {
  label: string;
  value: number;
}

export interface KeywordItem {
  word: string;
  count: number;
}

export interface OverviewResponse {
  risk_rate: number;
  high_risk_cnt: number;
  total_users: number;
  trend: TrendPoint[];
  top_keywords: KeywordItem[];
  complaint_mix: CountItem[];
  latest_snapshot: string;
  api_configured: boolean;
  langchain_rag_enabled: boolean;
  llm_model: string;
  rag_status: string;
  data_query_backend: string;
  langgraph_enabled: boolean;
  redis_available?: boolean;
  auth_enforced?: boolean;
  cache?: {
    hit: boolean;
    key: string;
    backend: string;
  };
}

export interface SchemaColumn {
  name: string;
  type: string;
  description: string;
  filterable?: boolean;
  dimension?: boolean;
}

export interface SchemaTable {
  name: string;
  description: string;
  default_scope: string;
  columns: SchemaColumn[];
}

export interface SchemaMetric {
  name: string;
  expression: string;
  description: string;
}

export interface SchemaCatalog {
  tables: SchemaTable[];
  filterable_dimensions: string[];
  allowed_filters: string[];
  metrics: SchemaMetric[];
  safety: {
    mode: string;
    allowed_statements: string[];
    rejected_keywords: string[];
    validator: string;
  };
}

export interface DailyRiskMetric {
  label: string;
  value: string | number;
}

export interface DailyRiskItem {
  category: string;
  complaint_type: string;
  order_count: number;
  compensation_total: number;
  share: number;
  reason?: string;
}

export interface DailyRiskCase {
  order_id: string;
  user_id: string;
  category: string;
  complaint_type: string;
  compensation_amount: number;
  comment: string;
}

export interface DailyRiskReport {
  report_id: string;
  report_date: string;
  generated_at: string;
  headline: string;
  metrics: DailyRiskMetric[];
  top_risks: DailyRiskItem[];
  top_cases: DailyRiskCase[];
  recommended_actions: string[];
  delivery_mock: {
    channel: string;
    status: string;
    schedule?: string;
    note?: string;
  };
  markdown: string;
}

export interface SampleQuestion {
  mode: ChatMode;
  text: string;
}

export interface MetricItem {
  label: string;
  value: string | number;
}

export interface TicketRow {
  order_id: string;
  user_id: string;
  category: string;
  complaint_type: string;
  compensation_amount: number;
  pay_amount?: number;
  created_at: string;
  comment: string;
  ticket_count?: number;
  share_of_total?: number;
  reason?: string;
}

export interface Citation {
  label: string;
  text: string;
  retrieval_score?: number;
  rerank_score?: number;
  rrf_score?: number;
  source?: string;
}

export interface CitationHighlight {
  citation_index: number;
  citation_label: string;
  answer_excerpt: string;
  match_score: number;
}

export interface ToolTraceItem {
  tool: string;
  arguments?: Record<string, unknown>;
  duration_ms?: number;
  result_summary?: string;
  structured_output?: Record<string, unknown>;
  token_usage?: TokenUsage;
  cost_breakdown?: CostBreakdown;
  timing?: Record<string, number>;
}

export interface TokenUsage {
  embedding_tokens?: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface CostBreakdown {
  embedding_cost_usd?: number;
  prompt_cost_usd?: number;
  completion_cost_usd?: number;
  total_cost_usd: number;
}

export interface ReviewCase {
  case_id: string;
  request_id: string;
  session_id?: string | null;
  user_role?: Role;
  source_mode?: string;
  reason?: string;
  user_message?: string;
  response_summary?: string | null;
  tool_trace?: ToolTraceItem[];
  case_priority?: 'low' | 'medium' | 'high' | 'critical';
  escalation_reason?: string | null;
  assignee?: string | null;
  status: ReviewStatus;
  reviewer_note?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface QueryRewriteInfo {
  original: string;
  rewritten: string;
  method: string;
  rewrite_ms: number;
}

export interface ReflectionResult {
  passed: boolean;
  issues: string[];
  retries: number;
}

export interface QueryPlanStep {
  step_id: number;
  query: string;
  expected_tool: string;
  depends_on?: number[];
}

export interface QueryPlanInfo {
  steps: QueryPlanStep[];
  decomposition_method: string;
}

export interface AgentDispatch {
  agent: string;
  called: boolean;
}

export interface OnlineRAGMetricsInfo {
  retrieval_diversity: number;
  retrieval_confidence: number;
  coverage_score: number;
  has_citations: boolean;
  query_rewrite_applied: boolean;
}

export interface ModularRAGMetricsInfo {
  activated_modules: string[];
  skipped_modules: string[];
  module_timings: Record<string, number>;
  retrieval_strategy: string;
  kg_entities: string[];
  kg_triples: number;
  crag_status: string;
  self_rag_passed: boolean;
}

export interface ChatResponse {
  mode: string;
  title: string;
  summary: string;
  session_id?: string | null;
  metrics?: MetricItem[];
  table?: TicketRow[];
  sql_preview?: string;
  highlights?: string[];
  citations?: Citation[];
  citation_highlights?: CitationHighlight[];
  tool_trace?: ToolTraceItem[];
  review_required?: boolean;
  review_reason?: string;
  review_case?: ReviewCase;
  request_id?: string;
  trace_id?: string;
  latency_ms?: number;
  token_usage?: TokenUsage;
  cost_breakdown?: CostBreakdown;
  estimated_cost_usd?: number;
  retry_count?: number;
  response_language?: ResponseLanguage;
  trace?: Record<string, unknown>;
  error?: ApiErrorPayload;
  degradation_path?: string | null;
  route?: {
    mode: string;
    reason?: string;
    confidence?: number;
    source?: string;
  };
  graph_trace?: string[];
  graph_engine?: string;
  agent_dispatch?: AgentDispatch[];
  query_rewrite?: QueryRewriteInfo;
  reflection?: ReflectionResult;
  query_plan?: QueryPlanInfo;
  retrieval_mode?: string;
  online_rag_metrics?: OnlineRAGMetricsInfo;
  modular_rag_metrics?: ModularRAGMetricsInfo;
}

export interface ChatRequest {
  message: string;
  mode: ChatMode;
  session_id?: string | null;
  role?: Role;
  response_language?: ResponseLanguage;
}

export interface FeedbackRequest {
  request_id: string;
  session_id?: string | null;
  rating: 'up' | 'down';
  comment?: string;
  role?: Role;
}

export interface StreamStatusPayload {
  phase: string;
  message: string;
}

export interface ReviewQueueResponse {
  items: ReviewCase[];
  error?: ApiErrorPayload;
}

export interface ReviewDecisionResponse {
  item?: ReviewCase;
  error?: ApiErrorPayload;
}

export interface AuditEvent {
  request_id: string;
  trace_id?: string | null;
  session_id?: string | null;
  mode: string;
  route_mode?: string | null;
  route_source?: string | null;
  route_confidence?: number | null;
  route_reason?: string | null;
  blocked_by_guardrail: boolean;
  blocked_by_permission: boolean;
  user_role: Role;
  user_message: string;
  response_title?: string | null;
  tool_trace: ToolTraceItem[];
  sql_preview?: string | null;
  latency_ms: number;
  token_usage?: Partial<TokenUsage>;
  estimated_cost_usd: number;
  retry_count: number;
  created_at: string;
}

export interface AuditRecentResponse {
  items: AuditEvent[];
  error?: ApiErrorPayload;
}

export interface EvalCaseTotal {
  all_cases: number;
  rag_cases: number;
  route_cases: number;
  tool_cases: number;
  guardrail_cases: number;
  memory_cases: number;
}

export interface EvalMetrics {
  route_accuracy: number;
  tool_selection_accuracy: number;
  citation_hit_rate: number;
  rag_case_success_rate: number;
  negative_abstention_rate: number;
  guardrail_interception: number;
  memory_followup_accuracy: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  retry_success_rate: number;
}

export interface EvalRagRow {
  question: string;
  tag?: string;
  expected_doc_id?: string;
  returned_doc_ids?: string[];
  hit?: boolean;
  retrieval_mode?: string;
}

export interface EvalRouteRow {
  question: string;
  tag?: string;
  expected_mode?: string;
  actual_mode?: string;
  hit?: boolean;
}

export interface EvalToolRow {
  question: string;
  tag?: string;
  expected_tool?: string;
  actual_tool?: string;
  hit?: boolean;
}

export interface EvalGuardrailRow {
  question: string;
  tag?: string;
  blocked?: boolean;
  expected_blocked?: boolean;
}

export interface EvalMemoryRow {
  question?: string;
  followup?: string;
  expected_tool?: string;
  actual_tool?: string;
  hit?: boolean;
}

export interface EvalReport {
  total: EvalCaseTotal;
  metrics: EvalMetrics;
  rag_available: boolean;
  rag_status: string;
  evaluation_mode: string;
  generated_at?: string;
  report_path?: string;
  rows: {
    rag: EvalRagRow[];
    route: EvalRouteRow[];
    tool: EvalToolRow[];
    guardrail: EvalGuardrailRow[];
    memory: EvalMemoryRow[];
  };
  error?: ApiErrorPayload;
}

// ── Document Management ──────────────────────────────────────────────

export interface DocumentInfo {
  filename: string;
  size_bytes: number;
  modified_at: string;
  extension: string;
}

export interface DocumentUploadResponse {
  filename: string;
  sections_parsed: number;
  sections_after_cleaning: number;
  chunks_created: number;
  error?: ApiErrorPayload;
}

export interface DocumentListResponse {
  items: DocumentInfo[];
  total: number;
}

export interface LineageStep {
  step_name: string;
  timestamp: string;
  duration_ms: number;
}

export interface LineageRecord {
  chunk_id: string;
  source_file: string;
  source_page: number | null;
  source_section: string;
  processing_steps: LineageStep[];
  created_at: string;
}

export interface DocumentLineageResponse {
  filename: string;
  chunks: number;
  lineages: LineageRecord[];
}

export interface VersionRecord {
  version_id: string;
  branch: string;
  parent_id: string | null;
  timestamp: string;
  message: string;
  author: string;
  chunk_count: number;
  added: number;
  removed: number;
  modified: number;
}

export interface VersionListResponse {
  items: VersionRecord[];
}

export interface VersionCreateResponse {
  version: {
    version_id: string;
    chunk_count: number;
    timestamp: string;
  };
}

export interface DocumentAuditEvent {
  event_id: string;
  timestamp: string;
  category: string;
  action: string;
  actor: string;
  target: string;
  details: Record<string, unknown>;
  result: string;
}

export interface DocumentAuditResponse {
  items: DocumentAuditEvent[];
}

export interface DocumentAuditStats {
  total_events: number;
  by_category: Record<string, number>;
  by_result: Record<string, number>;
  recent_24h: number;
  retention_days: number;
}
