import type {
  ChatRequest,
  ChatResponse,
  AuditRecentResponse,
  DailyRiskReport,
  DocumentAuditResponse,
  DocumentAuditStats,
  DocumentLineageResponse,
  DocumentListResponse,
  DocumentUploadResponse,
  EvalReport,
  LoginResponse,
  OverviewResponse,
  ReviewDecisionResponse,
  ReviewQueueResponse,
  ReviewStatus,
  SampleQuestion,
  SchemaCatalog,
  StreamStatusPayload,
  VersionCreateResponse,
  VersionListResponse,
} from '@/types/api';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const TOKEN_KEY = 'copilot_access_token';

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

function authHeaders(options?: RequestInit) {
  const headers = new Headers(options?.headers || {});
  const token = localStorage.getItem(TOKEN_KEY);
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return headers;
}

async function errorMessage(response: Response) {
  try {
    const payload = await response.json();
    return payload?.detail?.message || payload?.detail?.code || payload?.error?.message || payload?.error?.code || `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

export async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { ...options, headers: authHeaders(options) });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json() as Promise<T>;
}

export function login(username: string, password: string) {
  return fetchJson<LoginResponse>('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function getMe() {
  return fetchJson<{ user: LoginResponse['user'] }>('/api/auth/me');
}

export function getOverview() {
  return fetchJson<OverviewResponse>('/api/overview');
}

export function getSchema() {
  return fetchJson<SchemaCatalog>('/api/schema');
}

export function getDailyRiskReport() {
  return fetchJson<DailyRiskReport>('/api/reports/daily-risk');
}

export async function getSampleQuestions() {
  const payload = await fetchJson<{ items: SampleQuestion[] }>('/api/sample-questions');
  return payload.items || [];
}

export function postChat(request: ChatRequest) {
  return fetchJson<ChatResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export async function streamChat(
  request: ChatRequest,
  handlers: {
    onStatus?: (payload: StreamStatusPayload) => void;
    onToken?: (content: string) => void;
    onFinal?: (payload: ChatResponse) => void;
  } = {},
) {
  const response = await fetch(apiUrl('/api/chat/stream'), {
    method: 'POST',
    headers: authHeaders({ headers: { 'Content-Type': 'application/json' } }),
    body: JSON.stringify(request),
  });

  if (!response.ok || !response.body) {
    throw new Error(await errorMessage(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let finalPayload: ChatResponse | null = null;

  const consumeBlock = (block: string) => {
    const lines = block.split(/\r?\n/).filter(Boolean);
    const eventName = lines.find((line) => line.startsWith('event:'))?.replace('event:', '').trim();
    const dataText = lines
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.replace('data:', '').trim())
      .join('\n');

    if (!eventName || !dataText) return;

    if (eventName === 'token') {
      const data = JSON.parse(dataText) as { content?: string };
      if (data.content) handlers.onToken?.(data.content);
      return;
    }

    const data = JSON.parse(dataText) as StreamStatusPayload | ChatResponse;
    if (eventName === 'status') {
      handlers.onStatus?.(data as StreamStatusPayload);
    }
    if (eventName === 'final') {
      finalPayload = data as ChatResponse;
      handlers.onFinal?.(finalPayload);
    }
    if (eventName === 'error') {
      throw new Error((data as StreamStatusPayload).message || 'Stream response error');
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() || '';
    parts.forEach(consumeBlock);
  }

  if (buffer.trim()) {
    consumeBlock(buffer);
  }

  if (!finalPayload) {
    throw new Error('Stream response did not return a final payload');
  }
  return finalPayload;
}

export function getReviewQueue(status: ReviewStatus) {
  return fetchJson<ReviewQueueResponse>(`/api/review/queue?limit=50&status=${status}&role=supervisor`);
}

export function getAuditRecent(limit = 50, role = 'analyst') {
  return fetchJson<AuditRecentResponse>(`/api/audit/recent?limit=${limit}&role=${encodeURIComponent(role)}`);
}

export function getEvalReport(role = 'analyst') {
  return fetchJson<EvalReport>(`/api/eval/report?role=${encodeURIComponent(role)}`);
}

export function updateReviewCase(caseId: string, status: ReviewStatus, reviewerNote: string, assignee?: string, casePriority?: string) {
  return fetchJson<ReviewDecisionResponse>(`/api/review/queue/${encodeURIComponent(caseId)}/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, reviewer_note: reviewerNote, role: 'supervisor', assignee, case_priority: casePriority }),
  });
}

export function postFeedback(requestId: string, rating: 'up' | 'down', comment?: string, sessionId?: string) {
  return fetchJson<{ item: Record<string, unknown> }>('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, rating, comment, session_id: sessionId }),
  });
}

// ── Document Management ──────────────────────────────────────────────

export function listDocuments() {
  return fetchJson<DocumentListResponse>('/api/documents');
}

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(apiUrl('/api/documents'), {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json();
}

export function deleteDocument(filename: string) {
  return fetchJson<{ deleted: string }>(`/api/documents/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
}

export function getDocumentLineage(filename: string) {
  return fetchJson<DocumentLineageResponse>(`/api/documents/${encodeURIComponent(filename)}/lineage`);
}

export function listVersions(branch?: string) {
  const params = branch ? `?branch=${encodeURIComponent(branch)}` : '';
  return fetchJson<VersionListResponse>(`/api/versions${params}`);
}

export function createVersion() {
  return fetchJson<VersionCreateResponse>('/api/versions', { method: 'POST' });
}

export function rollbackVersion(versionId: string) {
  return fetchJson<{ restored: string; chunks: number }>(`/api/versions/${encodeURIComponent(versionId)}/rollback`, {
    method: 'POST',
  });
}

export function getDocumentAudit(params?: { category?: string; action?: string; limit?: number }) {
  const searchParams = new URLSearchParams();
  if (params?.category) searchParams.set('category', params.category);
  if (params?.action) searchParams.set('action', params.action);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  const qs = searchParams.toString();
  return fetchJson<DocumentAuditResponse>(`/api/document-audit${qs ? '?' + qs : ''}`);
}

export function getDocumentAuditStats() {
  return fetchJson<DocumentAuditStats>('/api/document-audit/stats');
}
