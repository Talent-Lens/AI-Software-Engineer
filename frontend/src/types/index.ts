export type ActiveTab = 'explorer' | 'langgraph' | 'diff' | 'eval' | 'settings';
export type UIMode = 'simple' | 'advanced';

export interface CodeFile {
  id: string;
  name: string;
  path: string;
  language: string;
  originalCode: string;
  proposedFix: string;
  hasBug: boolean;
  hasSecurityRisk: boolean;
  docstringStatus: 'missing' | 'generated' | 'verified';
  lineCitations: { line: number; text: string; status: 'verified' | 'hallucinated' }[];
  securityIssues: { severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'; title: string; line: number; rule: string; cwe?: string; description?: string; remediation?: string }[];
}

export type GraphNodeStatus = 'idle' | 'running' | 'success' | 'error';

export interface GraphNode {
  id: string;
  name: string;
  description: string;
  category: 'retrieval' | 'agent' | 'verifier' | 'sandbox';
  status: GraphNodeStatus;
  durationMs?: number;
  inputPayload?: any;
  outputPayload?: any;
  logs?: string[];
}

export interface PipelineExecutionState {
  isExecuting: boolean;
  activeNodeId: string | null;
  logs: string[];
  nodes: Record<string, GraphNode>;
  traceId?: string;
  startTime?: string;
  endTime?: string;
}

export interface RAGTriadMetrics {
  meanContextRecall: number;
  meanContextPrecision: number;
  meanFaithfulness: number;
  meanF1Score?: number;
  meanMrr: number;
  hitsAt1Rate: number;
  hitsAt3Rate: number;
  hitsAt5Rate: number;
  hitsAt10Rate: number;
}

export interface BenchmarkTestCase {
  testCaseId: string;
  query: string;
  contextRecall: number;
  contextPrecision: number;
  faithfulness: number;
  f1Score?: number;
  reciprocalRank: number;
  hitsAt1: number;
  hitsAt3: number;
  hitsAt5: number;
  hitsAt10: number;
  generatedAnswer: string;
  retrievedChunkIds: string[];
}

export interface EvalReport {
  timestamp: string;
  totalTestCases: number;
  metrics: RAGTriadMetrics;
  results: BenchmarkTestCase[];
}

export interface UserFeedbackRequest {
  chunk_id: string;
  user_action: 'accept' | 'reject';
  feedback_note?: string;
  user_id?: string;
}

export type ChecklistStatus = 'PASS' | 'FAIL' | 'MANUAL_REVIEW' | 'NOT_APPLICABLE';
export type ChecklistSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export interface ChecklistItem {
  id: string;
  title: string;
  category: string;
  status: ChecklistStatus;
  severity: ChecklistSeverity;
  explanation: string;
  remediation: string;
  filePath?: string;
  file_path?: string;
  lineNumber?: number;
  line_number?: number;
  snippet?: string;
  manualReviewReason?: string;
  manual_review_reason?: string;
}

export interface LaunchChecklistReport {
  timestamp: string;
  totalChecks: number;
  total_checks?: number;
  passedCount: number;
  passed_count?: number;
  failedCount: number;
  failed_count?: number;
  manualReviewCount: number;
  manual_review_count?: number;
  notApplicableCount: number;
  not_applicable_count?: number;
  readinessPercentage: number;
  readiness_percentage?: number;
  grade: string;
  launchStatus: 'LAUNCH_READY' | 'NEEDS_REVIEW' | 'BLOCK_DEPLOYMENT';
  launch_status?: string;
  summary: string;
  items: ChecklistItem[];
  categorySummary?: Record<string, { total: number; passed: number; failed: number; manual: number; na: number }>;
  category_summary?: Record<string, { total: number; passed: number; failed: number; manual: number; na: number }>;
}
