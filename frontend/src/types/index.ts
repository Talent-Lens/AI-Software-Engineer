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
