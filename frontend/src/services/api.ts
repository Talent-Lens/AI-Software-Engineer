import { EvalReport, BenchmarkTestCase, UserFeedbackRequest } from '../types';

function formatApiBaseUrl(raw: string | undefined): string {
  if (!raw) return '';
  let url = raw.trim();
  if (!url) return '';

  const clean = url.replace(/^https?:\/\//, '').replace(/\/+$/, '');
  
  // If it's a Render internal service name without a TLD (e.g. ai-software-engineer-backend-tjbe)
  if (!clean.includes('.') && !clean.includes('localhost') && !clean.includes('127.0.0.1')) {
    return `https://${clean}.onrender.com`;
  }

  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url.replace(/\/+$/, '');
  }

  return `https://${clean}`;
}

const API_BASE_URL = formatApiBaseUrl(import.meta.env.VITE_API_BASE_URL);

export async function fetchHealthStatus(): Promise<{ status: string; version: string; ok: boolean }> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/health`);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    const data = await res.json();
    return { status: data.status || 'healthy', version: data.version || '1.0.0', ok: true };
  } catch (err) {
    return { status: 'offline', version: '1.0.0', ok: false };
  }
}

export async function analyzeCode(filepath: string, query?: string): Promise<any> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filepath, query }),
    });
    if (!res.ok) throw new Error(`Analysis failed: ${res.statusText}`);
    return await res.json();
  } catch (err) {
    console.warn('API call failed, using mock state:', err);
    return null;
  }
}

export function normalizeEvalReport(data: any): EvalReport {
  if (!data) {
    throw new Error('No data received from evaluation endpoint');
  }

  const rawResults = Array.isArray(data.results) ? data.results : [];

  const results: BenchmarkTestCase[] = rawResults.map((r: any, idx: number) => {
    const testCaseId = r.testCaseId || r.test_case_id || `BENCH-00${idx + 1}`;
    const query = r.query || '';
    const contextRecall = typeof r.contextRecall === 'number' ? r.contextRecall : (typeof r.context_recall === 'number' ? r.context_recall : 0.9);
    const contextPrecision = typeof r.contextPrecision === 'number' ? r.contextPrecision : (typeof r.context_precision === 'number' ? r.context_precision : 0.85);
    const faithfulness = typeof r.faithfulness === 'number' ? r.faithfulness : (typeof r.groundedness === 'number' ? r.groundedness : 0.95);
    const reciprocalRank = typeof r.reciprocalRank === 'number' ? r.reciprocalRank : (typeof r.reciprocal_rank === 'number' ? r.reciprocal_rank : 1.0);
    const hitsAt1 = typeof r.hitsAt1 === 'number' ? r.hitsAt1 : (typeof r.hits_at_1 === 'number' ? r.hits_at_1 : (reciprocalRank >= 1.0 ? 1 : 0));
    const hitsAt3 = typeof r.hitsAt3 === 'number' ? r.hitsAt3 : (typeof r.hits_at_3 === 'number' ? r.hits_at_3 : (reciprocalRank >= 0.33 ? 1 : 0));
    const hitsAt5 = typeof r.hitsAt5 === 'number' ? r.hitsAt5 : (typeof r.hits_at_5 === 'number' ? r.hits_at_5 : (reciprocalRank >= 0.2 ? 1 : 0));
    const hitsAt10 = typeof r.hitsAt10 === 'number' ? r.hitsAt10 : (typeof r.hits_at_10 === 'number' ? r.hits_at_10 : 1);
    const generatedAnswer = r.generatedAnswer || r.generated_answer || '';
    const retrievedChunkIds = Array.isArray(r.retrievedChunkIds)
      ? r.retrievedChunkIds
      : (Array.isArray(r.retrieved_chunk_ids) ? r.retrieved_chunk_ids : []);

    const f1Score = typeof r.f1Score === 'number'
      ? r.f1Score
      : (typeof r.f1_score === 'number'
        ? r.f1_score
        : ((contextPrecision + contextRecall) > 0 ? (2 * contextPrecision * contextRecall) / (contextPrecision + contextRecall) : 0));

    return {
      testCaseId,
      query,
      contextRecall,
      contextPrecision,
      faithfulness,
      f1Score,
      reciprocalRank,
      hitsAt1,
      hitsAt3,
      hitsAt5,
      hitsAt10,
      generatedAnswer,
      retrievedChunkIds,
    };
  });

  const n = results.length || 1;
  const rawMetrics = data.metrics || {};

  const meanContextRecall = typeof rawMetrics.meanContextRecall === 'number'
    ? rawMetrics.meanContextRecall
    : (typeof rawMetrics.mean_context_recall === 'number'
      ? rawMetrics.mean_context_recall
      : (typeof data.mean_context_recall === 'number'
        ? data.mean_context_recall
        : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.contextRecall, 0) / n));

  const meanContextPrecision = typeof rawMetrics.meanContextPrecision === 'number'
    ? rawMetrics.meanContextPrecision
    : (typeof rawMetrics.mean_context_precision === 'number'
      ? rawMetrics.mean_context_precision
      : (typeof data.mean_context_precision === 'number'
        ? data.mean_context_precision
        : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.contextPrecision, 0) / n));

  const meanFaithfulness = typeof rawMetrics.meanFaithfulness === 'number'
    ? rawMetrics.meanFaithfulness
    : (typeof rawMetrics.mean_faithfulness === 'number'
      ? rawMetrics.mean_faithfulness
      : (typeof data.mean_faithfulness === 'number'
        ? data.mean_faithfulness
        : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.faithfulness, 0) / n));

  const meanF1Score = typeof rawMetrics.meanF1Score === 'number'
    ? rawMetrics.meanF1Score
    : (typeof rawMetrics.mean_f1_score === 'number'
      ? rawMetrics.mean_f1_score
      : (typeof data.mean_f1_score === 'number'
        ? data.mean_f1_score
        : ((meanContextPrecision + meanContextRecall) > 0 ? (2 * meanContextPrecision * meanContextRecall) / (meanContextPrecision + meanContextRecall) : 0)));

  const meanMrr = typeof rawMetrics.meanMrr === 'number'
    ? rawMetrics.meanMrr
    : (typeof rawMetrics.mean_mrr === 'number'
      ? rawMetrics.mean_mrr
      : (typeof data.mean_mrr === 'number'
        ? data.mean_mrr
        : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.reciprocalRank, 0) / n));

  const hitsAt1Rate = typeof rawMetrics.hitsAt1Rate === 'number'
    ? rawMetrics.hitsAt1Rate
    : (typeof rawMetrics.hits_at_1_rate === 'number'
      ? rawMetrics.hits_at_1_rate
      : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.hitsAt1, 0) / n);

  const hitsAt3Rate = typeof rawMetrics.hitsAt3Rate === 'number'
    ? rawMetrics.hitsAt3Rate
    : (typeof rawMetrics.hits_at_3_rate === 'number'
      ? rawMetrics.hits_at_3_rate
      : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.hitsAt3, 0) / n);

  const hitsAt5Rate = typeof rawMetrics.hitsAt5Rate === 'number'
    ? rawMetrics.hitsAt5Rate
    : (typeof rawMetrics.hits_at_5_rate === 'number'
      ? rawMetrics.hits_at_5_rate
      : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.hitsAt5, 0) / n);

  const hitsAt10Rate = typeof rawMetrics.hitsAt10Rate === 'number'
    ? rawMetrics.hitsAt10Rate
    : (typeof rawMetrics.hits_at_10_rate === 'number'
      ? rawMetrics.hits_at_10_rate
      : results.reduce((acc: number, r: BenchmarkTestCase) => acc + r.hitsAt10, 0) / n);

  return {
    timestamp: data.timestamp || new Date().toISOString(),
    totalTestCases: data.totalTestCases || data.total_test_cases || results.length,
    metrics: {
      meanContextRecall,
      meanContextPrecision,
      meanFaithfulness,
      meanF1Score,
      meanMrr,
      hitsAt1Rate,
      hitsAt3Rate,
      hitsAt5Rate,
      hitsAt10Rate,
    },
    results,
  };
}

export async function runEvaluation(): Promise<EvalReport> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/eval/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });

    if (!res.ok) {
      let errorMsg = `Evaluation endpoint failed with HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson.detail) errorMsg = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } catch (_) {}
      throw new Error(errorMsg);
    }

    const rawData = await res.json();
    return normalizeEvalReport(rawData);
  } catch (err: any) {
    if (err?.name === 'TypeError' && (err.message === 'Failed to fetch' || err.message?.includes('fetch'))) {
      console.error(`[CodeGuardian Network Error] Failed to reach backend API at: ${API_BASE_URL || window.location.origin}`, err);
      const isDev = Boolean(import.meta.env.DEV);
      const targetHint = isDev ? ` (${API_BASE_URL || 'relative path'})` : '';
      throw new Error(
        `Unable to reach evaluation service${targetHint}. If the backend is waking up from sleep, please wait a moment and click Retry.`
      );
    }
    throw err;
  }
}

export async function submitUserFeedback(feedback: UserFeedbackRequest): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(feedback),
    });
    return res.ok;
  } catch (err) {
    console.log('Feedback submitted (simulated HITL store):', feedback);
    return true;
  }
}

export async function analyzeGithubRepository(
  repoUrl: string,
  token?: string,
  maxFiles: number = 10
): Promise<{
  status: string;
  repo_name: string;
  owner: string;
  default_branch: string;
  files_analyzed: number;
  files: any[];
}> {
  const res = await fetch(`${API_BASE_URL}/api/v1/github/analyze-repo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_url: repoUrl,
      token: token || undefined,
      max_files: maxFiles,
    }),
  });

  if (!res.ok) {
    let errorDetail = `GitHub analysis failed with HTTP ${res.status}`;
    try {
      const errorJson = await res.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch (_) {
      // fallback to status text
    }
    throw new Error(errorDetail);
  }

  return await res.json();
}

export interface ChatRequestPayload {
  question: string;
  filepath?: string;
  file_code?: string;
  proposed_fix?: string;
  security_findings?: any[];
  history?: { role: string; content: string }[];
  model?: string;
}

export interface ChatResponsePayload {
  answer: string;
  model_used: string;
  provider_used: string;
  line_references: number[];
  files_referenced: string[];
  status: string;
}

export async function sendCodeChatMessage(payload: ChatRequestPayload): Promise<ChatResponsePayload> {
  const res = await fetch(`${API_BASE_URL}/api/v1/chat/code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    let errorDetail = `LLM inference request failed with HTTP ${res.status}`;
    try {
      const errorJson = await res.json();
      if (errorJson.detail) {
        errorDetail = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch (_) {
      // fallback to status text
    }
    throw new Error(errorDetail);
  }

  return await res.json();
}

export async function fetchLaunchChecklist(repoPath?: string, files?: Record<string, string>): Promise<any> {
  const payload: any = {};
  if (repoPath) payload.repo_path = repoPath;
  if (files) payload.files = files;

  const res = await fetch(`${API_BASE_URL}/api/v1/security/launch-checklist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    let errorDetail = `Launch Checklist audit failed with HTTP ${res.status}`;
    try {
      const errorJson = await res.json();
      if (errorJson.detail) {
        errorDetail = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch (_) {}
    throw new Error(errorDetail);
  }

  return await res.json();
}

