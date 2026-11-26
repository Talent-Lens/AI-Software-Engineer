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

export interface RepoBenchmarkDetail {
  file: string;
  line: string;
  issue?: string;
  severity?: string;
  [key: string]: any;
}

export interface RepoBenchmarkMetrics {
  total_cases: number;
  detected_cases: number;
  false_positives: number;
  precision: number;
  recall: number;
  f1_score: number;
  details: RepoBenchmarkDetail[];
}

export interface RepoBenchmarkResponse {
  status: string;
  repo_url: string;
  test_type: string;
  metrics: RepoBenchmarkMetrics;
  timestamp: string;
}

export interface SampledPrecisionStats {
  sampled_precision: number | null;
  ci_low: number | null;
  ci_high: number | null;
  true_vuln: number;
  false_alarm: number;
  uncertain: number;
  n_decided: number;
  n_total: number;
}

export interface BenchmarkToolMetrics {
  precision: number | null;
  sampled_precision?: SampledPrecisionStats | null;
  recall: number | null;
  f1_score?: number | null;
  false_positive_rate: number;
  zero_findings_only?: boolean;
  localization_accuracy: number | null;
  classification_accuracy: number | null;
  classification_family_accuracy?: number | null;
  scan_latency: number | null;
  latency_spread?: number | null;
  latency_measured?: boolean;
  ast_latency?: number | null;
  codeql_db_create_median_s?: number | null;
  codeql_analyze_median_s?: number | null;
  end_to_end_latency?: number | null;
  latency_scope?: string | null;
  latency_measurement_mode?: string;
  tool_version: string;
  sample_size: number;
  sample_counts?: Record<string, number>;
  has_data?: boolean;
  status?: string;
  status_detail?: string | null;
}

export interface BenchmarkLatencyPassInfo {
  id: string;
  pass_version: number;
  status: string;
  repeats: number;
  repo_ids: string[];
  host_info: {
    cpu_model?: string;
    cpu_cores_logical?: number;
    cpu_cores_physical?: number;
    ram_gb?: number | null;
    os?: string;
    machine?: string;
  };
  stale?: boolean;
  stale_reasons?: string[];
  started_at?: string | null;
  completed_at?: string | null;
  results?: {
    per_tool_macro?: Record<string, any>;
    per_repo?: Record<string, any>;
  };
}

export interface BenchmarkCapabilitiesResponse {
  benchmark_mode: 'readonly' | 'research';
  readonly: boolean;
  can_mutate: boolean;
  can_run: boolean;
  can_add: boolean;
  can_recompute: boolean;
  can_triage: boolean;
  can_latency_pass: boolean;
}

export interface BenchmarkOverviewResponse {
  total_repos: number;
  verified_repos: number;
  provisional_repos: number;
  verified_only?: boolean;
  has_provisional?: boolean;
  fpr_is_upper_bound?: boolean;
  total_loc: number;
  sanity_warnings?: string[];
  tools: Record<string, BenchmarkToolMetrics>;
  latency_pass?: BenchmarkLatencyPassInfo | null;
  active_latency_pass?: BenchmarkLatencyPassInfo | null;
  snapshot?: {
    snapshot_id: string;
    schema_version: string;
    sha256: string;
    generated_at: string;
    repos_count: number;
    imported_at?: string | null;
  } | null;
  generated_at: string;
}

export interface ResearchRepoItem {
  id: string;
  name: string;
  url: string;
  pinned_sha?: string | null;
  clean_sha?: string | null;
  cve_id?: string;
  repo_type?: string;
  fix_commit?: string;
  parent_commit?: string;
  language: string;
  loc?: number | null;
  status: string;
  label_quality?: 'provisional' | 'verified';
  is_excluded?: boolean;
  exclusion_reason?: string;
  job_stage?: string;
  job_progress?: number;
  job_error?: string;
  last_heartbeat?: string | null;
  ignored_candidates?: any[];
  notes?: string;
  metrics?: Record<string, any>;
  required_tools?: string[];
  tools_ran?: string[];
  tool_statuses?: Record<string, {
    status: string;
    tool_version?: string;
    duration_s?: number;
    error_message?: string | null;
    required?: boolean;
    cached?: boolean;
    original_timestamp?: string | null;
    original_duration_s?: number | null;
  }>;
  completed_runs_count?: number;
  has_completed_run?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface BenchmarkRunPlanTool {
  tool: string;
  action: 'reuse' | 'rescan';
  reason?: string;
  cached_run_id?: string | null;
  tool_version: string;
  ruleset_id?: string | null;
  scope_policy_hash: string;
  original_timestamp?: string | null;
  original_duration_s?: number | null;
}

export interface BenchmarkRunPlanResponse {
  repo_id: string;
  repo_name: string;
  force_rescan: boolean;
  scope_policy_hash: string;
  reuse: string[];
  rescan: string[];
  tools: BenchmarkRunPlanTool[];
}

export interface ResearchRepoDetailResponse {
  repo: ResearchRepoItem;
  ground_truth: any;
  metrics: Record<string, any>;
  runs: any[];
  findings: any[];
  stage_timings?: Record<string, any>;
}

export interface UserPublic {
  id: string;
  email: string;
  username: string;
  display_name?: string;
  avatar_url?: string;
  role: string;
  created_at?: string;
}

export interface AuthState {
  user: UserPublic | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

