import React, { useState, useEffect, useRef } from 'react';
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer, 
  RadarChart, 
  PolarGrid, 
  PolarAngleAxis, 
  PolarRadiusAxis, 
  Radar, 
  Legend,
  LabelList
} from 'recharts';
import { 
  ShieldCheck, 
  Target, 
  Clock, 
  AlertTriangle, 
  Layers, 
  FileCode, 
  CheckCircle2, 
  XCircle, 
  ExternalLink, 
  HelpCircle, 
  ChevronRight, 
  RefreshCw,
  Search,
  Filter,
  Info,
  GitBranch,
  BarChart2,
  Check,
  X,
  Plus,
  Play,
  RotateCw,
  Ban,
  Download,
  Upload,
  EyeOff,
  Eye,
  Trash2,
  AlertCircle
} from 'lucide-react';
import { BenchmarkCapabilitiesResponse, BenchmarkOverviewResponse, BenchmarkRunPlanResponse, ResearchRepoItem, ResearchRepoDetailResponse } from '../types';
import { 
  fetchBenchmarkCapabilities,
  fetchBenchmarkOverview, 
  fetchResearchRepos, 
  fetchResearchRepoDetail,
  fetchBenchmarkRunPlan,
  addResearchRepo,
  runResearchRepo,
  retryResearchRepo,
  recomputeResearchRepo,
  excludeResearchRepo,
  unexcludeResearchRepo,
  deleteResearchRepo,
  exportBlindTriage,
  importVerifiedTriage,
  startLatencyPass
} from '../services/api';

const TOOL_DISPLAY: Record<string, { name: string; color: string; badge: string; isSubject?: boolean; isReference?: boolean }> = {
  codeguardian: { name: 'CodeGuardian (Our Engine)', color: '#6366f1', badge: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30', isSubject: true },
  semgrep: { name: 'Semgrep OSS 1.74', color: '#10b981', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' },
  codeql: { name: 'GitHub CodeQL 2.16', color: '#38bdf8', badge: 'bg-sky-500/10 text-sky-400 border-sky-500/30' },
  sonarqube: { name: 'SonarQube Community 10.4', color: '#f59e0b', badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30' },
  bandit: { name: 'Bandit 1.8.6 (Python Reference Line)', color: '#94a3b8', badge: 'bg-slate-500/10 text-slate-400 border-slate-500/30', isReference: true },
};

export const EvalDashboard: React.FC = () => {
  const [overview, setOverview] = useState<BenchmarkOverviewResponse | null>(null);
  const [repos, setRepos] = useState<ResearchRepoItem[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState<string | null>(null);
  const [repoDetail, setRepoDetail] = useState<ResearchRepoDetailResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showMethodologyModal, setShowMethodologyModal] = useState<boolean>(false);
  const [findingSearch, setFindingSearch] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'overview' | 'drilldown'>('overview');
  const [verifiedOnly, setVerifiedOnly] = useState<boolean>(false);
  const [forceRescan, setForceRescan] = useState<boolean>(false);
  const [latencyPassStarting, setLatencyPassStarting] = useState<boolean>(false);
  const [capabilities, setCapabilities] = useState<BenchmarkCapabilitiesResponse>({
    benchmark_mode: 'readonly',
    readonly: true,
    can_mutate: false,
    can_run: false,
    can_add: false,
    can_recompute: false,
    can_triage: false,
    can_latency_pass: false,
  });

  // Add Repository Modal State
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [addUrl, setAddUrl] = useState<string>('');
  const [addIdentifier, setAddIdentifier] = useState<string>('');
  const [addCwe, setAddCwe] = useState<string>('');
  const [isAdding, setIsAdding] = useState<boolean>(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Exclude Modal State
  const [showExcludeModal, setShowExcludeModal] = useState<boolean>(false);
  const [repoToExclude, setRepoToExclude] = useState<ResearchRepoItem | null>(null);
  const [excludeReason, setExcludeReason] = useState<string>('');
  const [isExcluding, setIsExcluding] = useState<boolean>(false);
  const [showExcluded, setShowExcluded] = useState<boolean>(false);

  // Delete Modal State
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [repoToDelete, setRepoToDelete] = useState<ResearchRepoItem | null>(null);
  const [deleteReason, setDeleteReason] = useState<string>('');
  const [isDeleting, setIsDeleting] = useState<boolean>(false);

  const [runningRepoIds, setRunningRepoIds] = useState<Set<string>>(new Set());

  // Blind Triage State
  const [triageUploadLoading, setTriageUploadLoading] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isFetchingRef = useRef<boolean>(false);

  const loadData = async (isVerifiedOnly = verifiedOnly, silent = false) => {
    if (silent && isFetchingRef.current) return;
    isFetchingRef.current = true;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [overviewData, reposData, capsData] = await Promise.all([
        fetchBenchmarkOverview(isVerifiedOnly),
        fetchResearchRepos(),
        fetchBenchmarkCapabilities(),
      ]);
      setOverview(overviewData);
      setRepos(reposData);
      setCapabilities(capsData);
      if (reposData.length > 0 && !selectedRepoId) {
        setSelectedRepoId(reposData[0].id);
      }
    } catch (err: any) {
      console.error('Failed to load benchmark data:', err);
      setError(err?.message || 'Failed to load research benchmark metrics.');
    } finally {
      isFetchingRef.current = false;
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [verifiedOnly]);

  // Live progress polling only in mutable research mode when a repo is actively running
  useEffect(() => {
    if (capabilities.readonly) return;
    const hasRunningJobs = repos.some(
      (r) =>
        r.status === 'running' ||
        (r.job_stage && !['done', 'failed', 'needs_attention', 'partial'].includes(r.job_stage))
    );
    if (!hasRunningJobs) return;

    const interval = setInterval(() => {
      loadData(verifiedOnly, true);
    }, 3000);
    return () => clearInterval(interval);
  }, [repos, verifiedOnly, capabilities.readonly]);

  const handleSelectRepo = async (repoId: string) => {
    setSelectedRepoId(repoId);
    setDetailLoading(true);
    try {
      const detail = await fetchResearchRepoDetail(repoId);
      setRepoDetail(detail);
      setActiveTab('drilldown');
    } catch (err: any) {
      console.error('Failed to load repo detail:', err);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleUrlChange = (val: string) => {
    const trimmed = val.trim();
    // Auto-extract owner/repo and pre-fill commit SHA if user pasted a commit URL
    const commitMatch = trimmed.match(/github\.com\/([^\/]+)\/([^\/]+)\/commit\/([0-9a-fA-F]{7,40})/);
    if (commitMatch) {
      const [, owner, repo, sha] = commitMatch;
      setAddUrl(`https://github.com/${owner}/${repo}`);
      if (!addIdentifier.trim()) {
        setAddIdentifier(sha);
      }
      return;
    }
    setAddUrl(val);
  };

  const handleIdentifierChange = (val: string) => {
    const trimmed = val.trim();
    // Auto-extract CVE identifier if user pasted an NVD or MITRE URL
    const cveMatch = trimmed.match(/\b(CVE-\d{4}-\d{4,8})\b/i);
    if (cveMatch && trimmed.startsWith('http')) {
      setAddIdentifier(cveMatch[1].toUpperCase());
      return;
    }
    const ghsaMatch = trimmed.match(/\b(GHSA-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4})\b/i);
    if (ghsaMatch && trimmed.startsWith('http')) {
      setAddIdentifier(ghsaMatch[1].toUpperCase());
      return;
    }
    setAddIdentifier(val);
  };

  const handleAddRepo = async (e: React.FormEvent) => {
    e.preventDefault();
    let url = addUrl.trim();
    let identifier = addIdentifier.trim();
    if (!url || !identifier) return;

    // Safety extraction if full URLs were left in inputs
    const commitMatch = url.match(/github\.com\/([^\/]+)\/([^\/]+)\/commit\/([0-9a-fA-F]{7,40})/);
    if (commitMatch) {
      const [, owner, repo, sha] = commitMatch;
      url = `https://github.com/${owner}/${repo}`;
      if (!identifier) identifier = sha;
    }
    const cveMatch = identifier.match(/\b(CVE-\d{4}-\d{4,8})\b/i);
    if (cveMatch && identifier.startsWith('http')) {
      identifier = cveMatch[1].toUpperCase();
    }

    setIsAdding(true);
    setAddError(null);
    try {
      await addResearchRepo(url, identifier, addCwe);
      setShowAddModal(false);
      setAddUrl('');
      setAddIdentifier('');
      setAddCwe('');
      await loadData();
    } catch (err: any) {
      setAddError(err?.message || 'Failed to queue repository.');
    } finally {
      setIsAdding(false);
    }
  };

  const handleRetry = async (repoId: string) => {
    try {
      await retryResearchRepo(repoId, forceRescan);
      await loadData();
    } catch (err: any) {
      alert(`Retry failed: ${err.message}`);
    }
  };

  const handleRunBenchmark = async (repo: ResearchRepoItem) => {
    if (runningRepoIds.has(repo.id) || repo.status === 'running') return;
    let planSummary = '';
    try {
      const plan: BenchmarkRunPlanResponse = await fetchBenchmarkRunPlan(repo.id, forceRescan);
      const planTools = Array.isArray(plan.tools) ? plan.tools : [];
      const reuseLines = planTools
        .filter((t) => t.action === 'reuse')
        .map((t) => {
          const ts = t.original_timestamp ? new Date(t.original_timestamp).toLocaleString() : 'previous run';
          const dur = t.original_duration_s != null ? `${Number(t.original_duration_s).toFixed(2)}s` : 'n/a';
          return `  - ${t.tool}: REUSE cached result (${ts}, ${dur})`;
        });
      const scanLines = planTools
        .filter((t) => t.action !== 'reuse')
        .map((t) => `  - ${t.tool}: RE-SCAN (${t.reason || 'cache miss'})`);
      planSummary = `\n\nExecution Plan${plan.force_rescan ? ' (Force full re-scan)' : ''}:\n${[...reuseLines, ...scanLines].join('\n')}`;
    } catch {
      planSummary = forceRescan ? '\n\n(Force full re-scan enabled — ignoring cached tool results)' : '';
    }
    const isRerun = repo.status === 'done' || repo.status === 'partial';
    const confirmed = window.confirm(
      isRerun
        ? `Run benchmark pipeline for "${repo.name}"?${planSummary}`
        : `Start the full automated benchmark pipeline for "${repo.name}"?${planSummary}`
    );
    if (!confirmed) return;

    setRunningRepoIds((prev) => new Set(prev).add(repo.id));
    try {
      await runResearchRepo(repo.id, forceRescan);
      await loadData();
    } catch (err: any) {
      alert(`Pipeline execution failed: ${err.message}`);
    } finally {
      setRunningRepoIds((prev) => {
        const next = new Set(prev);
        next.delete(repo.id);
        return next;
      });
    }
  };

  const handleExcludeSubmit = async () => {
    if (!repoToExclude || !excludeReason.trim() || excludeReason.trim().length < 5) {
      alert('Please enter a specific reason of at least 5 characters.');
      return;
    }
    setIsExcluding(true);
    try {
      await excludeResearchRepo(repoToExclude.id, excludeReason.trim());
      setShowExcludeModal(false);
      setRepoToExclude(null);
      setExcludeReason('');
      await loadData();
    } catch (err: any) {
      alert(`Exclude failed: ${err.message}`);
    } finally {
      setIsExcluding(false);
    }
  };

  const handleUnexclude = async (repoId: string) => {
    try {
      await unexcludeResearchRepo(repoId);
      await loadData();
    } catch (err: any) {
      alert(`Re-include failed: ${err.message}`);
    }
  };

  const handleDeleteSubmit = async () => {
    if (!repoToDelete) return;
    const needsReason = Boolean(repoToDelete.has_completed_run || (repoToDelete.completed_runs_count ?? 0) > 0);
    if (needsReason && deleteReason.trim().length < 5) {
      alert('A specific written reason (at least 5 characters) is required because this repository has completed runs.');
      return;
    }
    setIsDeleting(true);
    try {
      await deleteResearchRepo(repoToDelete.id, deleteReason.trim() || undefined);
      if (selectedRepoId === repoToDelete.id) {
        setSelectedRepoId(null);
        setRepoDetail(null);
      }
      setShowDeleteModal(false);
      setRepoToDelete(null);
      setDeleteReason('');
      await loadData();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleExportBlindTriage = async (repoId: string) => {
    try {
      const data = await exportBlindTriage(repoId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `blind_triage_${data.repo_name.replace('/', '_')}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(`Export failed: ${err.message}`);
    }
  };

  const handleImportBlindTriage = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedRepoId) return;
    setTriageUploadLoading(true);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const findings = parsed.findings || parsed;
      await importVerifiedTriage(selectedRepoId, findings);
      await loadData();
      if (selectedRepoId) await handleSelectRepo(selectedRepoId);
      alert('Successfully imported verified labels! Repository is now verified.');
    } catch (err: any) {
      alert(`Failed to import triage decisions: ${err.message}`);
    } finally {
      setTriageUploadLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Tools & Metric processing
  const tools = overview?.tools || {};
  const cgMetrics = tools['codeguardian'];
  const semgrepMetrics = tools['semgrep'];
  const hasCgData = Boolean(cgMetrics?.has_data && cgMetrics?.sample_size > 0);

  const formatStage = (stage?: string) => {
    switch (stage) {
      case 'queued': return 'Queued';
      case 'resolving': return 'Resolving';
      case 'cloning': return 'Cloning';
      case 'labeling': return 'Labeling';
      case 'scanning': return 'Scanning';
      case 'scanning_clean': return 'Scanning Clean';
      case 'computing': return 'Computing';
      case 'needs_attention': return 'Needs Attention';
      case 'done': return 'Done';
      default: return stage || 'Processing';
    }
  };

  const formatRelativeTime = (timestamp?: string | null) => {
    if (!timestamp) return '';
    const diffMs = Date.now() - new Date(timestamp).getTime();
    const diffSec = Math.max(0, Math.floor(diffMs / 1000));
    if (diffSec < 60) return `updated ${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `updated ${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    return `updated ${diffHr}h ago`;
  };

  // 1. Radar Chart Data (undefined axes kept as null so Recharts never plots n/a as 0)
  const radarMetricVal = (v: number | null | undefined) => (v != null ? Math.round(v * 100) : null);
  const cleanSpecVal = (t: any) =>
    t?.has_data && !(t?.zero_findings_only && t?.false_positive_rate === 0)
      ? Math.max(0, Math.round(100 - (t?.false_positive_rate || 0) * 10))
      : null;

  const radarData = [
    {
      metric: 'Precision',
      codeguardian: radarMetricVal(tools['codeguardian']?.precision),
      semgrep: radarMetricVal(tools['semgrep']?.precision),
      codeql: radarMetricVal(tools['codeql']?.precision),
      sonarqube: radarMetricVal(tools['sonarqube']?.precision),
      bandit: radarMetricVal(tools['bandit']?.precision),
    },
    {
      metric: 'Recall',
      codeguardian: radarMetricVal(tools['codeguardian']?.recall),
      semgrep: radarMetricVal(tools['semgrep']?.recall),
      codeql: radarMetricVal(tools['codeql']?.recall),
      sonarqube: radarMetricVal(tools['sonarqube']?.recall),
      bandit: radarMetricVal(tools['bandit']?.recall),
    },
    {
      metric: 'F1 Score',
      codeguardian: radarMetricVal(tools['codeguardian']?.f1_score),
      semgrep: radarMetricVal(tools['semgrep']?.f1_score),
      codeql: radarMetricVal(tools['codeql']?.f1_score),
      sonarqube: radarMetricVal(tools['sonarqube']?.f1_score),
      bandit: radarMetricVal(tools['bandit']?.f1_score),
    },
    {
      metric: 'Clean Specificity',
      codeguardian: cleanSpecVal(tools['codeguardian']),
      semgrep: cleanSpecVal(tools['semgrep']),
      codeql: cleanSpecVal(tools['codeql']),
      sonarqube: cleanSpecVal(tools['sonarqube']),
      bandit: cleanSpecVal(tools['bandit']),
    },
    {
      metric: 'Localization ±3L',
      codeguardian: radarMetricVal(tools['codeguardian']?.localization_accuracy),
      semgrep: radarMetricVal(tools['semgrep']?.localization_accuracy),
      codeql: radarMetricVal(tools['codeql']?.localization_accuracy),
      sonarqube: radarMetricVal(tools['sonarqube']?.localization_accuracy),
      bandit: radarMetricVal(tools['bandit']?.localization_accuracy),
    },
    {
      metric: 'CWE Classification',
      codeguardian: radarMetricVal(tools['codeguardian']?.classification_accuracy),
      semgrep: radarMetricVal(tools['semgrep']?.classification_accuracy),
      codeql: radarMetricVal(tools['codeql']?.classification_accuracy),
      sonarqube: radarMetricVal(tools['sonarqube']?.classification_accuracy),
      bandit: radarMetricVal(tools['bandit']?.classification_accuracy),
    },
  ];

  // 2. Bar Chart Data (filtered to tools with completed runs; keeps 0-anchor for n/a so LabelList renders explicit '0%' / 'n/a')
  const barData = Object.keys(tools)
    .filter((key) => tools[key]?.has_data)
    .map((key) => {
      const t = tools[key];
      const info = TOOL_DISPLAY[key] || { name: key };
      return {
        key,
        tool: info.name.split(' ')[0],
        Precision: t.precision != null ? Math.round(t.precision * 100) : 0,
        Recall: t.recall != null ? Math.round(t.recall * 100) : 0,
        Localization: t.localization_accuracy != null ? Math.round(t.localization_accuracy * 100) : 0,
        Classification: t.classification_accuracy != null ? Math.round(t.classification_accuracy * 100) : 0,
        isNa: {
          Precision: t.precision == null,
          Recall: t.recall == null,
          Localization: t.localization_accuracy == null,
          Classification: t.classification_accuracy == null,
        } as Record<string, boolean>,
        sampleSize: t.sample_size ?? 0,
        definedCounts: {
          Precision: t.sample_counts?.precision ?? 0,
          Recall: t.sample_counts?.recall ?? 0,
          Localization: t.sample_counts?.localization_accuracy ?? 0,
          Classification: t.sample_counts?.classification_accuracy ?? 0,
        } as Record<string, number>,
        precisionLabel: t.precision != null ? `${Math.round(t.precision * 100)}%` : 'n/a',
        recallLabel: t.recall != null ? `${Math.round(t.recall * 100)}%` : 'n/a',
        localizationLabel: t.localization_accuracy != null ? `${Math.round(t.localization_accuracy * 100)}%` : 'n/a',
        classificationLabel: t.classification_accuracy != null ? `${Math.round(t.classification_accuracy * 100)}%` : 'n/a',
        f1Label: t.f1_score != null ? `${(t.f1_score * 100).toFixed(1)}%` : 'n/a',
      };
    });

  const handleStartLatencyPass = async () => {
    const activeRepos = repos.filter((r) => !r.is_excluded && (r.status === 'done' || r.status === 'partial'));
    if (activeRepos.length === 0) {
      alert('No completed or partial active repositories available for a latency pass.');
      return;
    }
    const repoList = activeRepos.map((r) => `  - ${r.name}`).join('\n');
    const confirmed = window.confirm(
      `Start an isolated sequential Latency Pass (3 repeats per installed tool on vulnerable commits)?\n\nSelected repositories (${activeRepos.length}):\n${repoList}\n\nNothing else from the benchmark system may run concurrently. On aiohttp + joblib + setuptools this takes roughly ~65–70 minutes (mostly CodeQL 3×).`
    );
    if (!confirmed) return;

    setLatencyPassStarting(true);
    try {
      await startLatencyPass(activeRepos.map((r) => r.id), 3);
      await loadData(verifiedOnly);
    } catch (err: any) {
      alert(`Latency pass failed to start: ${err.message}`);
    } finally {
      setLatencyPassStarting(false);
    }
  };

  // 3. Scan Latency Data (strictly from isolated Latency Pass, never from detection runs)
  const latencyPass = overview?.latency_pass || null;
  const latencyPassDate = latencyPass?.completed_at ? new Date(latencyPass.completed_at).toLocaleString() : null;
  const latencyHostLabel = latencyPass?.host_info
    ? `${latencyPass.host_info.cpu_model || 'unknown CPU'} (${latencyPass.host_info.cpu_cores_logical ?? '?'} cores, ${latencyPass.host_info.ram_gb ?? '?'} GB RAM, ${latencyPass.host_info.os || 'unknown OS'})`
    : null;

  const latencyData = Object.keys(tools)
    .filter((key) => tools[key]?.latency_measured && tools[key]?.scan_latency != null)
    .map((key) => {
      const t = tools[key];
      const info = TOOL_DISPLAY[key] || { name: key, color: '#6366f1' };
      return {
        key,
        tool: key === 'codeguardian' ? 'CodeGuardian (AST)' : info.name.split(' (')[0],
        latency: t.scan_latency,
        spread: t.latency_spread ?? 0,
        dbCreate: t.codeql_db_create_median_s ?? null,
        analyze: t.codeql_analyze_median_s ?? null,
        scope: t.latency_scope || 'Scan-only',
        color: info.color,
      };
    });

  return (
    <div className="w-full h-full overflow-y-auto bg-slate-950 text-slate-100 p-6 md:p-8 space-y-8">
      {/* Top Banner / Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white flex items-center gap-2">
              <ShieldCheck className="w-8 h-8 text-indigo-400" />
              Scientific Security Benchmark
            </h1>
            <span className="px-2.5 py-1 text-xs font-semibold uppercase tracking-wider rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
              Automated Flow v2.2
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-400">
            {loading && !overview ? (
              <div className="flex items-center gap-3 animate-pulse">
                <div className="h-4 w-56 rounded bg-slate-800" />
                <div className="h-5 w-48 rounded bg-slate-800/80" />
                <div className="h-4 w-24 rounded bg-slate-800/60" />
              </div>
            ) : (
              <>
                <span>
                  Sample Size: <strong className="text-white">{overview?.total_repos || 0} repos</strong> ({overview?.verified_repos || 0} verified, {overview?.provisional_repos || 0} provisional) • <strong className="text-white">{(overview?.total_loc || 0).toLocaleString()} LOC</strong>
                </span>
                <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-700 text-[11px] text-slate-300">
                  {`Results snapshot generated ${new Date(overview?.snapshot?.generated_at || overview?.generated_at || Date.now()).toLocaleDateString()} • exploratory, N=${overview?.total_repos ?? 0}`}
                </span>
                <div className="flex items-center gap-1.5 ml-2 pl-3 border-l border-slate-800">
                  <label className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={verifiedOnly}
                      onChange={(e) => setVerifiedOnly(e.target.checked)}
                      className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                    />
                    <span className={verifiedOnly ? 'text-indigo-400 font-semibold' : 'text-slate-400'}>
                      Verified Only
                    </span>
                  </label>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {!capabilities.readonly && (
            <>
              <button
                onClick={handleStartLatencyPass}
                disabled={latencyPassStarting || Boolean(overview?.active_latency_pass) || repos.some((r) => r.status === 'running')}
                title={
                  overview?.active_latency_pass
                    ? `Latency pass v${overview.active_latency_pass.pass_version} is currently running`
                    : repos.some((r) => r.status === 'running')
                    ? 'Disabled while a detection pipeline is running'
                    : 'Run 3 sequential repeats per installed tool on vulnerable commits in isolation'
                }
                className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-cyan-600/20 hover:bg-cyan-600/30 border border-cyan-500/40 text-cyan-300 text-xs font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Clock className={`w-4 h-4 ${overview?.active_latency_pass ? 'animate-spin' : ''}`} />
                {overview?.active_latency_pass ? `Latency Pass v${overview.active_latency_pass.pass_version} Running...` : 'Latency Pass'}
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition shadow-lg shadow-indigo-600/20"
              >
                <Plus className="w-4 h-4" />
                Add Research Repo
              </button>
            </>
          )}
          <button
            onClick={() => setShowMethodologyModal(true)}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-300 hover:text-white text-xs font-medium transition"
          >
            <HelpCircle className="w-4 h-4 text-indigo-400" />
            Methodology
          </button>
          <button
            onClick={() => loadData(verifiedOnly)}
            disabled={loading}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-300 hover:text-white text-xs font-medium transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* SANITY WARNINGS BANNER */}
      {overview?.sanity_warnings && overview.sanity_warnings.length > 0 && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs space-y-1">
          <div className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>Benchmark Statistical Alerts & Sanity Checks:</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-slate-300 pl-6">
            {overview.sanity_warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-sm flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading && !overview ? (
        <div className="space-y-8 animate-pulse" aria-label="Loading benchmark dashboard">
          {/* Skeleton Tabs */}
          <div className="flex items-center gap-6 border-b border-slate-800 pb-3">
            <div className="h-5 w-44 rounded bg-slate-800" />
            <div className="h-5 w-52 rounded bg-slate-800/70" />
          </div>

          {/* Skeleton Top 6 KPI Cards */}
          <div>
            <div className="h-4 w-80 rounded bg-slate-800 mb-3" />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
              {Array.from({ length: 6 }).map((_, idx) => (
                <div
                  key={idx}
                  className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex flex-col justify-between min-h-[144px]"
                >
                  <div className="flex items-center justify-between">
                    <div className="h-3.5 w-28 rounded bg-slate-800" />
                    <div className="h-4 w-4 rounded-full bg-slate-800" />
                  </div>
                  <div className="my-3 space-y-2">
                    <div className="h-7 w-20 rounded bg-slate-800" />
                    <div className="h-3 w-32 rounded bg-slate-800/70" />
                  </div>
                  <div className="h-2.5 w-full rounded bg-slate-800/60" />
                </div>
              ))}
            </div>
          </div>

          {/* Skeleton Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {Array.from({ length: 3 }).map((_, idx) => (
              <div
                key={idx}
                className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 h-[340px] flex flex-col justify-between"
              >
                <div className="space-y-2">
                  <div className="h-4 w-48 rounded bg-slate-800" />
                  <div className="h-3 w-64 rounded bg-slate-800/70" />
                </div>
                <div className="flex-1 my-4 rounded-lg bg-slate-800/40 border border-slate-800/60" />
                <div className="flex items-center justify-center gap-4">
                  <div className="h-3 w-16 rounded bg-slate-800/70" />
                  <div className="h-3 w-16 rounded bg-slate-800/70" />
                  <div className="h-3 w-16 rounded bg-slate-800/70" />
                </div>
              </div>
            ))}
          </div>

          {/* Skeleton Breakdown Table */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="h-4 w-56 rounded bg-slate-800" />
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, idx) => (
                <div key={idx} className="h-10 w-full rounded bg-slate-800/50" />
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Navigation Tabs */}
          <div className="flex items-center gap-4 border-b border-slate-800">
            <button
              onClick={() => setActiveTab('overview')}
              className={`pb-3 text-sm font-semibold transition border-b-2 flex items-center gap-2 ${
                activeTab === 'overview'
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <BarChart2 className="w-4 h-4" />
              General Averages ({overview?.total_repos || 0} Repos)
            </button>
            <button
              onClick={() => {
                if (repos.length > 0 && !selectedRepoId) {
                  handleSelectRepo(repos[0].id);
                } else if (selectedRepoId && !repoDetail) {
                  handleSelectRepo(selectedRepoId);
                } else {
                  setActiveTab('drilldown');
                }
              }}
              className={`pb-3 text-sm font-semibold transition border-b-2 flex items-center gap-2 ${
                activeTab === 'drilldown'
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="w-4 h-4" />
              Per-Repository Ground Truth & Triage
            </button>
          </div>

          {activeTab === 'overview' ? (
        <>
          {/* SECTION 1: TOP 6 MACRO-AVERAGE KPI CARDS */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                The Six Standardized Evaluation Metrics (Macro-Averages • exploratory, N={overview?.total_repos ?? 0} {overview?.total_repos === 1 ? 'repo' : 'repos'})
              </h2>
              {overview?.fpr_is_upper_bound && (
                <span className="text-xs text-amber-400 flex items-center gap-1 font-medium bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                  <Info className="w-3.5 h-3.5" />
                  Clean FPR is an Upper Bound (includes provisional repos)
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
              {/* 1. Precision */}
              <div
                className="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition"
                title="Lower bound: TP / (TP + FP) evaluated strictly against fix-commit diff hunks. Unmatched findings are counted as FP here, though some may be real pre-existing vulnerabilities."
              >
                <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium">1. Precision vs. fix-labeled lines (lower bound)</span>
                  <Target className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                </div>
                <div
                  className="text-2xl font-bold text-white flex items-baseline gap-2 flex-wrap"
                  title={!hasCgData ? 'No completed runs' : cgMetrics?.precision == null ? 'Undefined: 0 findings reported on vulnerable commit (0/0)' : undefined}
                >
                  <span>{!hasCgData ? '-' : cgMetrics?.precision != null ? `${(cgMetrics.precision * 100).toFixed(1)}%` : 'n/a'}</span>
                  {hasCgData && cgMetrics?.sampled_precision && cgMetrics.sampled_precision.sampled_precision != null && (
                    <span
                      className="text-xs font-semibold text-teal-400 font-mono"
                      title={`Blinded sampled precision (n=${cgMetrics.sampled_precision.n_decided} decided, ${cgMetrics.sampled_precision.uncertain} uncertain excluded from denominator)`}
                    >
                      Sampled: {(cgMetrics.sampled_precision.sampled_precision * 100).toFixed(1)}%
                      {cgMetrics.sampled_precision.ci_low != null && cgMetrics.sampled_precision.ci_high != null
                        ? ` [${(cgMetrics.sampled_precision.ci_low * 100).toFixed(0)}–${(cgMetrics.sampled_precision.ci_high * 100).toFixed(0)}%]`
                        : ''}
                      {` (n=${cgMetrics.sampled_precision.n_decided})`}
                    </span>
                  )}
                </div>
                <div className="text-xs mt-1 flex items-center gap-1">
                  {hasCgData &&
                  (cgMetrics?.sample_counts?.precision ?? 0) >= 5 &&
                  (semgrepMetrics?.sample_counts?.precision ?? 0) >= 5 &&
                  cgMetrics?.precision != null &&
                  semgrepMetrics?.has_data &&
                  semgrepMetrics?.precision != null ? (
                    (() => {
                      const diff = cgMetrics.precision - semgrepMetrics.precision;
                      const nCg = cgMetrics.sample_counts!.precision;
                      const nSem = semgrepMetrics.sample_counts!.precision;
                      const se = Math.sqrt(
                        (cgMetrics.precision * (1 - cgMetrics.precision)) / nCg +
                          (semgrepMetrics.precision * (1 - semgrepMetrics.precision)) / nSem
                      );
                      const margin = 1.96 * se;
                      if (Math.abs(diff) <= margin) {
                        return (
                          <span className="text-slate-500">
                            {`${cgMetrics.sample_counts!.precision} / ${cgMetrics.sample_size} defined (Δ vs Semgrep within CI)`}
                          </span>
                        );
                      }
                      const pct = diff * 100;
                      const isPositive = pct > 0;
                      return (
                        <span className={isPositive ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold'}>
                          {isPositive ? `+${pct.toFixed(1)}% vs Semgrep` : `${pct.toFixed(1)}% vs Semgrep`}
                        </span>
                      );
                    })()
                  ) : (
                    <span className="text-slate-500">
                      {hasCgData
                        ? `${cgMetrics?.sample_counts?.precision ?? 0} / ${cgMetrics?.sample_size ?? 0} repos defined (vs Semgrep gated at N≥5)`
                        : 'No completed runs'}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-slate-500 mt-2 border-t border-slate-800/80 pt-2 font-mono">
                  TP / (TP + FP) lower bound • n/a if 0/0
                </p>
              </div>

              {/* 2. Recall & F1 */}
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition">
                <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium">2. Recall & F1</span>
                  <ShieldCheck className="w-4 h-4 text-indigo-400" />
                </div>
                <div className="text-2xl font-bold text-white">
                  {!hasCgData ? '-' : cgMetrics?.recall != null ? `${(cgMetrics.recall * 100).toFixed(1)}%` : 'n/a'}
                </div>
                <div
                  className="text-xs text-indigo-400 mt-1 flex items-center gap-1.5"
                  title="F1 = 2·P·R / (P+R); balances Recall against Precision so silent tools cannot score well"
                >
                  <span>
                    {hasCgData
                      ? `F1: ${cgMetrics?.f1_score != null ? `${(cgMetrics.f1_score * 100).toFixed(1)}%` : 'n/a'} (${cgMetrics?.sample_counts?.recall ?? 0} / ${cgMetrics?.sample_size ?? 0} defined)`
                      : 'No completed runs'}
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 mt-2 border-t border-slate-800/80 pt-2 font-mono">
                  TP / (TP + FN) • 0% if missed
                </p>
              </div>

              {/* 3. False Positive Rate */}
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition">
                <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium">3. False Positive Rate</span>
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                </div>
                <div className="text-2xl font-bold text-white">
                  {!hasCgData
                    ? '-'
                    : cgMetrics?.zero_findings_only && cgMetrics.false_positive_rate === 0
                    ? <span className="text-slate-400 text-lg font-semibold">no findings</span>
                    : cgMetrics!.false_positive_rate.toFixed(2)}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  {!hasCgData
                    ? 'No completed runs'
                    : cgMetrics?.zero_findings_only && cgMetrics.false_positive_rate === 0
                    ? `0 findings reported (${cgMetrics?.sample_counts?.false_positive_rate ?? 0} / ${cgMetrics?.sample_size ?? 0} defined)`
                    : `alarms / 1k LOC (${cgMetrics?.sample_counts?.false_positive_rate ?? 0} / ${cgMetrics?.sample_size ?? 0} defined)`}
                </div>
                <p className="text-[11px] text-slate-500 mt-2 border-t border-slate-800/80 pt-2 font-mono">
                  Clean-FP / kLOC {overview?.fpr_is_upper_bound ? '(Upper Bound)' : ''}
                </p>
              </div>

              {/* 4. Line Localization */}
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition">
                <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium">4. Localization</span>
                  <FileCode className="w-4 h-4 text-sky-400" />
                </div>
                <div
                  className="text-2xl font-bold text-white"
                  title={!hasCgData ? 'No completed runs' : cgMetrics?.localization_accuracy == null ? 'no true positives' : undefined}
                >
                  {!hasCgData ? '-' : cgMetrics?.localization_accuracy != null ? `${(cgMetrics.localization_accuracy * 100).toFixed(1)}%` : 'n/a'}
                </div>
                <div className="text-xs text-sky-400 mt-1" title={cgMetrics?.localization_accuracy == null ? 'no true positives' : undefined}>
                  {!hasCgData
                    ? 'No completed runs'
                    : cgMetrics?.localization_accuracy == null
                    ? `no true positives (0 / ${cgMetrics?.sample_size ?? 0} defined)`
                    : `within ±3 lines (${cgMetrics?.sample_counts?.localization_accuracy ?? 0} / ${cgMetrics?.sample_size ?? 0} defined)`}
                </div>
                <p className="text-[11px] text-slate-500 mt-2 border-t border-slate-800/80 pt-2 font-mono">
                  Among TPs only (TP &gt; 0)
                </p>
              </div>

              {/* 5. Classification Accuracy */}
              <div
                className="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition"
                title="Exact: same MITRE CWE or direct parent/child (e.g. CWE-95 under CWE-94). Family: shared MITRE top-level pillar (e.g. CWE-78 and CWE-94 in CWE-707 Injection). Kept strictly separate."
              >
                <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium">5. Classification</span>
                  <CheckCircle2 className="w-4 h-4 text-purple-400" />
                </div>
                <div
                  className="text-2xl font-bold text-white"
                  title={!hasCgData ? 'No completed runs' : cgMetrics?.classification_accuracy == null ? 'no true positives' : undefined}
                >
                  {!hasCgData ? '-' : cgMetrics?.classification_accuracy != null ? `${(cgMetrics.classification_accuracy * 100).toFixed(1)}%` : 'n/a'}
                </div>
                <div className="text-xs text-purple-400 mt-1" title={cgMetrics?.classification_accuracy == null ? 'no true positives' : undefined}>
                  {!hasCgData
                    ? 'No completed runs'
                    : cgMetrics?.classification_accuracy == null
                    ? `no true positives (0 / ${cgMetrics?.sample_size ?? 0} defined)`
                    : `Exact CWE (${cgMetrics?.sample_counts?.classification_accuracy ?? 0} / ${cgMetrics?.sample_size ?? 0} defined)`}
                </div>
                <p className="text-[11px] text-slate-400 mt-2 border-t border-slate-800/80 pt-2 font-mono">
                  Family: {!hasCgData ? '-' : cgMetrics?.classification_family_accuracy != null ? `${(cgMetrics.classification_family_accuracy * 100).toFixed(1)}%` : 'n/a'} • Exact ≠ Family
                </p>
              </div>

              {/* 6. Scan Latency (strictly from isolated Latency Pass) */}
              <div
                className="p-4 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition"
                title={
                  cgMetrics?.latency_measured && cgMetrics?.scan_latency != null && latencyPass
                    ? `Exact median: ${cgMetrics.scan_latency.toFixed(4)}s / 1k LOC (spread: ±${(cgMetrics.latency_spread ?? 0).toFixed(4)}s)\nIsolated Latency Pass v${latencyPass.pass_version} (${latencyPass.repeats} repeats) on ${latencyPassDate}\nHost: ${latencyHostLabel}${latencyPass.stale ? `\nSTALE: ${(latencyPass.stale_reasons || []).join('; ')}` : ''}`
                    : 'Not measured yet. Run a Latency Pass to measure isolated sequential scan latency.'
                }
              >
                <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium flex items-center gap-1.5">
                    6. Scan Latency
                    {latencyPass?.stale && (
                      <span
                        className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30"
                        title={(latencyPass.stale_reasons || []).join('; ')}
                      >
                        STALE
                      </span>
                    )}
                  </span>
                  <Clock className="w-4 h-4 text-cyan-400" />
                </div>
                <div className="text-2xl font-bold text-white">
                  {cgMetrics?.latency_measured && cgMetrics?.scan_latency != null
                    ? `${cgMetrics.scan_latency.toFixed(2)}s`
                    : 'not measured'}
                </div>
                <div className="text-xs text-cyan-400 mt-1">
                  {cgMetrics?.latency_measured && cgMetrics?.scan_latency != null
                    ? (cgMetrics.scan_latency < 0.1
                        ? 'AST engine only, under 0.1 s per 1k LOC'
                        : `AST engine only • ${latencyPass?.repeats ?? 3}× isolated pass`)
                    : 'Run Latency Pass to measure'}
                </div>
                <p className="text-[11px] text-slate-500 mt-2 border-t border-slate-800/80 pt-2 font-mono truncate">
                  {cgMetrics?.latency_measured && latencyPassDate
                    ? `Pass v${latencyPass?.pass_version} • ${latencyPassDate}`
                    : 'Isolated pass only (no detection-run durations)'}
                </p>
              </div>
            </div>
          </div>

          {/* SECTION 2: 3 COMPARISON VISUALIZATIONS */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Chart 1: Radar Chart */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-sm font-semibold text-white">Multi-Tool Radar Comparison</h3>
                  <p
                    className="text-xs text-slate-400"
                    title="Clean Specificity alone rewards silent tools; Recall and F1 Score (2·P·R/(P+R)) balance detection against false alarms."
                  >
                    6 dimensions (0–100) • includes Recall &amp; F1
                  </p>
                </div>
              </div>
              <div className="w-full h-72">
                {(overview?.total_repos ?? 0) >= 3 && Object.values(tools).some((t: any) => t?.has_data) ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="70%">
                      <PolarGrid stroke="#334155" />
                      <PolarAngleAxis dataKey="metric" stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                      <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#475569" />
                      {overview?.tools?.codeguardian?.has_data && (
                        <Radar name="CodeGuardian" dataKey="codeguardian" stroke="#6366f1" fill="#6366f1" fillOpacity={0.4} />
                      )}
                      {overview?.tools?.semgrep?.has_data && (
                        <Radar name="Semgrep" dataKey="semgrep" stroke="#10b981" fill="#10b981" fillOpacity={0.15} />
                      )}
                      {overview?.tools?.codeql?.has_data && (
                        <Radar name="CodeQL" dataKey="codeql" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.15} />
                      )}
                      {overview?.tools?.sonarqube?.has_data && (
                        <Radar name="SonarQube" dataKey="sonarqube" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.15} />
                      )}
                      {overview?.tools?.bandit?.has_data && (
                        <Radar name="Bandit" dataKey="bandit" stroke="#ec4899" fill="#ec4899" fillOpacity={0.15} />
                      )}
                      <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', fontSize: '12px' }}
                        formatter={(val: any) => (val == null ? 'n/a' : `${val}`)}
                      />
                    </RadarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4 text-slate-500 text-xs">
                    <BarChart2 className="w-8 h-8 mb-2 stroke-slate-600" />
                    <span>
                      {(overview?.total_repos ?? 0) < 3
                        ? `Radar chart hidden until at least 3 repos are in the averages (currently N=${overview?.total_repos ?? 0}).`
                        : 'No completed multi-tool evaluation runs available to plot.'}
                    </span>
                  </div>
                )}
              </div>
              {(overview?.total_repos ?? 0) >= 3 && Object.values(tools).some((t: any) => t?.has_data) && (() => {
                const activeKeys = Object.keys(tools).filter((k) => tools[k]?.has_data);
                const naAxes = radarData
                  .filter((row: any) => activeKeys.every((k) => row[k] == null))
                  .map((row) => row.metric);
                return naAxes.length > 0 ? (
                  <p className="text-[10px] font-mono text-slate-400 mt-2 pt-2 border-t border-slate-800">
                    Undefined axes (not plotted as 0): {naAxes.map((m) => `${m}: n/a`).join(' • ')}
                  </p>
                ) : null;
              })()}
            </div>

            {/* Chart 2: Grouped Bar Chart */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-sm font-semibold text-white">Detection & Accuracy Rates (%)</h3>
                  <p className="text-xs text-slate-400">Precision, Recall, Localization, Classification</p>
                  {(() => {
                    const missingParts = Object.entries(tools)
                      .filter(([, t]: [string, any]) => !t?.has_data)
                      .map(([k, t]: [string, any]) => {
                        const label = TOOL_DISPLAY[k]?.name?.split(' (')[0] || k;
                        const st = t?.status || 'not_installed';
                        if (st === 'docker_not_running') {
                          return `${label}: Docker daemon not running`;
                        }
                        if (k === 'semgrep' && st === 'not_installed') {
                          return `${label}: not installed`;
                        }
                        return `${label}: ${st.replace('_', ' ')}`;
                      });
                    return missingParts.length > 0 ? (
                      <p className="text-[10px] text-amber-400/90 font-mono mt-0.5">
                        ({missingParts.join(' • ')})
                      </p>
                    ) : null;
                  })()}
                </div>
              </div>
              <div className="w-full h-72">
                {barData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={barData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="tool" stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                      <YAxis stroke="#64748b" domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', fontSize: '12px' }}
                        formatter={(val: any, name: any, props: any) => {
                          const row = props?.payload || {};
                          const isNa = Boolean(row.isNa?.[name]);
                          const defined = row.definedCounts?.[name] ?? 0;
                          const total = row.sampleSize ?? 0;
                          const label = isNa ? 'n/a' : `${val}%`;
                          return [`${label} (${defined} / ${total} defined repos)`, name];
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                      {(['Precision', 'Recall', 'Localization', 'Classification'] as const).map((metricKey, idx) => {
                        const fills = ['#10b981', '#6366f1', '#38bdf8', '#a855f7'];
                        return (
                          <Bar key={metricKey} dataKey={metricKey} fill={fills[idx]} radius={[2, 2, 0, 0]}>
                            <LabelList
                              dataKey={metricKey}
                              content={(props: any) => {
                                const { x, y, width, value, index } = props;
                                const row = barData[index];
                                const isNa = Boolean(row?.isNa?.[metricKey]);
                                if (!isNa && value !== 0) return null;
                                return (
                                  <text
                                    x={Number(x) + Number(width) / 2}
                                    y={Number(y) - 4}
                                    textAnchor="middle"
                                    fill="#94a3b8"
                                    fontSize={9}
                                  >
                                    {isNa ? 'n/a' : '0%'}
                                  </text>
                                );
                              }}
                            />
                          </Bar>
                        );
                      })}
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4 text-slate-500 text-xs">
                    <BarChart2 className="w-8 h-8 mb-2 stroke-slate-600" />
                    <span>No tool accuracy data to display.</span>
                  </div>
                )}
              </div>
              {barData.length > 0 && (
                <div className="mt-3 pt-2 border-t border-slate-800 space-y-1">
                  {barData.map((row) => (
                    <div key={row.key} className="flex items-center justify-between text-[10px] font-mono text-slate-400">
                      <span className="text-slate-200 font-semibold">{row.tool}</span>
                      <span>
                        P:{row.precisionLabel} • R:{row.recallLabel} • F1:{row.f1Label} • Loc:{row.localizationLabel} • Cls:{row.classificationLabel}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Chart 3: Scan Latency Bar Chart (strictly from isolated Latency Pass) */}
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3
                    className="text-sm font-semibold text-white flex items-center gap-2"
                    title={
                      latencyPass
                        ? `Pass v${latencyPass.pass_version} (${latencyPassDate})\nHost: ${latencyHostLabel}`
                        : 'Reads exclusively from an isolated sequential Latency Pass (3 repeats per tool).'
                    }
                  >
                    <span>Scan Latency (Median Seconds / 1k LOC)</span>
                    {latencyPass?.stale && (
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30"
                        title={(latencyPass.stale_reasons || []).join('; ')}
                      >
                        STALE
                      </span>
                    )}
                  </h3>
                  <p className="text-xs text-slate-400">
                    {latencyPass
                      ? `Isolated ${latencyPass.repeats}× sequential pass • ${latencyPassDate} • ${latencyPass.host_info?.cpu_model || 'host'} (${latencyPass.host_info?.cpu_cores_logical ?? '?'} cores)`
                      : 'Reads only from isolated sequential Latency Pass (3 repeats) • not measured'}
                  </p>
                </div>
              </div>
              <div className="w-full h-72">
                {latencyData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={latencyData} layout="vertical" margin={{ top: 10, right: 20, left: 20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis type="number" stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                      <YAxis dataKey="tool" type="category" stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', fontSize: '12px' }}
                        formatter={(val: any, _name: any, props: any) => {
                          if (val == null) return 'not measured';
                          const p = props?.payload || {};
                          const parts = [`${Number(val).toFixed(2)}s / 1k LOC (spread: ${Number(p.spread ?? 0).toFixed(2)}s)`];
                          if (p.dbCreate != null || p.analyze != null) {
                            parts.push(`DB create: ${Number(p.dbCreate ?? 0).toFixed(1)}s, Analyze: ${Number(p.analyze ?? 0).toFixed(1)}s`);
                          }
                          if (latencyPassDate) parts.push(`Pass: ${latencyPassDate}`);
                          if (latencyHostLabel) parts.push(`Host: ${latencyHostLabel}`);
                          return [parts.join(' | '), 'Median Latency'];
                        }}
                      />
                      <Bar dataKey="latency" fill="#6366f1" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4 text-slate-500 text-xs">
                    <Clock className="w-8 h-8 mb-2 stroke-slate-600" />
                    <span>not measured — click "Latency Pass" to run 3 sequential repeats per tool.</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* SECTION 3: RESEARCH REPOSITORIES TABLE */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white">Research Benchmark Repositories</h2>
                <p className="text-xs text-slate-400">
                  Version-controlled manifests with pinned commit SHAs, automated noise filtering, and dual-commit scans.
                </p>
              </div>
              <div className="flex items-center gap-3">
                {!capabilities.readonly && (
                  <label className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 text-xs text-slate-300 cursor-pointer hover:border-slate-600 transition">
                    <input
                      type="checkbox"
                      checked={forceRescan}
                      onChange={(e) => setForceRescan(e.target.checked)}
                      className="rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
                    />
                    <span>Force full re-scan</span>
                  </label>
                )}
                {(() => {
                  const excludedCount = repos.filter((r) => r.is_excluded).length;
                  return excludedCount > 0 ? (
                    <button
                      onClick={() => setShowExcluded((prev) => !prev)}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${
                        showExcluded
                          ? 'bg-slate-800 border-indigo-500/40 text-indigo-300'
                          : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {showExcluded ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                      {showExcluded ? `Hide excluded (${excludedCount})` : `Show excluded (${excludedCount})`}
                    </button>
                  ) : null;
                })()}
              </div>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/70 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="px-4 py-3">Repository / CVE</th>
                    <th className="px-4 py-3">Quality</th>
                    <th className="px-4 py-3">Language</th>
                    <th className="px-4 py-3">LOC</th>
                    <th className="px-4 py-3">Vulnerable (N-1)</th>
                    <th className="px-4 py-3">Clean (Fix)</th>
                    <th className="px-4 py-3">CG Precision</th>
                    <th className="px-4 py-3">CG Recall</th>
                    <th className="px-4 py-3">Pipeline Status</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 text-slate-300">
                  {(() => {
                    const visibleRepos = showExcluded ? repos : repos.filter((r) => !r.is_excluded);
                    if (visibleRepos.length === 0) {
                      return (
                        <tr>
                          <td colSpan={10} className="px-4 py-8 text-center text-slate-500">
                            {repos.length === 0
                              ? 'No research benchmark repositories registered yet. Click "Add Research Repo" to begin.'
                              : 'All registered repositories are currently excluded. Toggle "Show excluded" above to view them.'}
                          </td>
                        </tr>
                      );
                    }
                    return visibleRepos.map((repo) => (
                    <tr key={repo.id} className={`hover:bg-slate-800/40 transition ${repo.is_excluded ? 'opacity-50' : ''}`}>
                      <td className="px-4 py-3.5">
                        <div className="font-medium text-white flex items-center gap-2">
                          <GitBranch className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                          <span>{repo.name}</span>
                        </div>
                        {repo.cve_id && (
                          <div className="text-[11px] font-mono text-indigo-400 mt-0.5">
                            {repo.cve_id}
                          </div>
                        )}
                        {(repo.cve_id === 'CVE-2018-18074' || repo.name.toLowerCase().includes('requests')) && (
                          <div className="text-[10px] text-amber-400/90 font-medium mt-1 inline-flex items-center gap-1 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                            <Info className="w-3 h-3 flex-shrink-0" />
                            <span>Auth header redirect logic flaw (non-AST)</span>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        {repo.label_quality === 'verified' ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                            Verified
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                            Provisional
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5 capitalize">{repo.language || '-'}</td>
                      <td className="px-4 py-3.5">{repo.loc && repo.loc > 0 ? repo.loc.toLocaleString() : '-'}</td>
                      <td className="px-4 py-3.5 font-mono text-[11px] text-slate-400">
                        {repo.pinned_sha && repo.pinned_sha !== 'resolving' ? `${repo.pinned_sha.slice(0, 8)}...` : '-'}
                      </td>
                      <td className="px-4 py-3.5 font-mono text-[11px] text-slate-400">
                        {repo.repo_type === 'intentionally_vulnerable' || !repo.clean_sha
                          ? 'N/A'
                          : (repo.clean_sha && repo.clean_sha !== 'resolving' ? `${repo.clean_sha.slice(0, 8)}...` : '-')}
                      </td>
                      <td className="px-4 py-3.5 font-semibold text-emerald-400">
                        {(repo.status === 'done' || repo.status === 'partial') && repo.metrics?.codeguardian
                          ? (repo.metrics.codeguardian.precision != null ? `${(repo.metrics.codeguardian.precision * 100).toFixed(1)}%` : 'n/a')
                          : '-'}
                      </td>
                      <td className="px-4 py-3.5 font-semibold text-indigo-400">
                        {(repo.status === 'done' || repo.status === 'partial') && repo.metrics?.codeguardian
                          ? (repo.metrics.codeguardian.recall != null ? `${(repo.metrics.codeguardian.recall * 100).toFixed(1)}%` : 'n/a')
                          : '-'}
                      </td>
                      <td className="px-4 py-3.5">
                        {repo.status === 'running' ? (
                          <div className="space-y-1">
                            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
                              <RotateCw className="w-3 h-3 animate-spin" />
                              {formatStage(repo.job_stage)} ({Math.round((repo.job_progress || 0.05) * 100)}%)
                            </span>
                            <div className="w-24 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                              <div className="h-full bg-indigo-500 transition-all duration-300" style={{ width: `${Math.round((repo.job_progress || 0.05) * 100)}%` }} />
                            </div>
                            {(repo.last_heartbeat || repo.updated_at) && (
                              <div className="text-[10px] text-slate-500">
                                {formatRelativeTime(repo.last_heartbeat || repo.updated_at)}
                              </div>
                            )}
                          </div>
                        ) : repo.status === 'ready' ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/30">
                            Ready
                          </span>
                        ) : repo.status === 'done' ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                            {repo.is_excluded ? 'Excluded' : 'Completed'}
                          </span>
                        ) : repo.status === 'partial' ? (
                          <div className="space-y-1">
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                              {repo.is_excluded ? 'Partial (Excluded)' : 'Partial'}
                            </span>
                            {repo.job_error && (
                              <p className="text-[10px] text-amber-300/90 max-w-xs break-words" title={repo.job_error}>
                                {repo.job_error}
                              </p>
                            )}
                          </div>
                        ) : repo.status === 'needs_attention' ? (
                          <div className="space-y-1">
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                              Needs Attention
                            </span>
                            {repo.job_error && (
                              <p className="text-[10px] text-amber-300 max-w-xs break-words" title={repo.job_error}>
                                {repo.job_error}
                              </p>
                            )}
                          </div>
                        ) : repo.status === 'failed' ? (
                          <div className="space-y-1">
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                              Failed ({formatStage(repo.job_stage)})
                            </span>
                            {repo.job_error ? (
                              <p className="text-[10px] text-rose-400 max-w-xs break-words" title={repo.job_error}>
                                {repo.job_error}
                              </p>
                            ) : (
                              <p className="text-[10px] text-rose-400/70 italic">Pipeline halted without error details</p>
                            )}
                          </div>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-700/50 text-slate-300 border border-slate-600/30">
                            Queued
                          </span>
                        )}
                        {repo.tools_ran && repo.tools_ran.length > 0 && (
                          <div className="text-[10px] text-slate-400 mt-1 font-mono">
                            Ran: {repo.tools_ran.join(', ')}
                          </div>
                        )}
                        {repo.tool_statuses && Object.keys(repo.tool_statuses).length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {Object.entries(repo.tool_statuses).map(([tKey, tInfo]) => {
                              const st = tInfo.status;
                              const isOpt = tInfo.required === false;
                              const pillCls =
                                st === 'completed'
                                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                                  : isOpt
                                  ? 'bg-slate-800/60 text-slate-500 border-slate-700/60'
                                  : st === 'timed_out' || st === 'docker_not_running'
                                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                                  : st === 'failed'
                                  ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                                  : st === 'running'
                                  ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30'
                                  : 'bg-slate-800 text-slate-500 border-slate-700';
                              const pillLabel =
                                st === 'completed'
                                  ? 'done'
                                  : st === 'docker_not_running'
                                  ? 'docker stopped'
                                  : st.replace('_', ' ');
                              const cachedNote = tInfo.cached
                                ? ` [cached from ${tInfo.original_timestamp ? new Date(tInfo.original_timestamp).toLocaleString() : 'prior run'}${tInfo.original_duration_s != null ? `, ${Number(tInfo.original_duration_s).toFixed(2)}s` : ''}]`
                                : '';
                              return (
                                <span
                                  key={tKey}
                                  title={(tInfo.error_message || `${tKey}${isOpt ? ' (optional)' : ''}: ${st} (${tInfo.duration_s ?? 0}s)`) + cachedNote}
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-mono border ${pillCls}`}
                                >
                                  {tKey}:{pillLabel}{tInfo.cached ? ' (cached)' : ''}{isOpt ? ' (opt)' : ''}
                                </span>
                              );
                            })}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-right space-x-2">
                        {!capabilities.readonly && (
                          <>
                            {/* Run / Re-run / Retry Button with Double-Click Protection */}
                            {repo.status === 'running' || runningRepoIds.has(repo.id) ? (
                          <button
                            disabled
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 text-slate-500 text-[11px] cursor-not-allowed opacity-75"
                          >
                            <RotateCw className="w-3 h-3 animate-spin" />
                            Running...
                          </button>
                        ) : repo.status === 'ready' ? (
                          <button
                            onClick={() => handleRunBenchmark(repo)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] font-medium transition shadow-sm shadow-indigo-500/20"
                            title="Start full automated pipeline"
                          >
                            <Play className="w-3 h-3 fill-current" />
                            Run Benchmark
                          </button>
                        ) : repo.status === 'failed' || repo.status === 'needs_attention' ? (
                          <button
                            onClick={() => handleRunBenchmark(repo)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition"
                            title="Retry pipeline"
                          >
                            <RotateCw className="w-3 h-3" />
                            Retry
                          </button>
                        ) : repo.status === 'done' || repo.status === 'partial' ? (
                          <>
                            <button
                              onClick={() => handleRunBenchmark(repo)}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition"
                              title="Re-run pipeline"
                            >
                              <RotateCw className="w-3 h-3" />
                              Re-run
                            </button>
                            <button
                              onClick={async () => {
                                try {
                                  await recomputeResearchRepo(repo.id);
                                  await loadData();
                                } catch (err: any) {
                                  alert(err?.message || 'Failed to recompute metrics');
                                }
                              }}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[11px] transition"
                              title="Recompute metrics from stored findings without re-scanning"
                            >
                              Recompute metrics
                            </button>
                          </>
                        ) : null}

                        {repo.is_excluded ? (
                          <button
                            onClick={() => handleUnexclude(repo.id)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px]"
                          >
                            Re-include
                          </button>
                        ) : (
                            <button
                              onClick={() => {
                                setRepoToExclude(repo);
                                setShowExcludeModal(true);
                              }}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 text-[11px]"
                              title="Exclude from macro-averages"
                            >
                              <Ban className="w-3 h-3" />
                            </button>
                          )}
                          </>
                        )}

                        <button
                          onClick={() => handleSelectRepo(repo.id)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-400 border border-indigo-500/30 text-xs font-medium transition"
                        >
                          Inspect
                          <ChevronRight className="w-3.5 h-3.5" />
                        </button>

                        {!capabilities.readonly && (repo.status !== 'running' && (repo.status === 'failed' || repo.status === 'needs_attention' || repo.status === 'ready' || repo.status === 'pending' || repo.is_excluded)) && (
                          <button
                            onClick={() => {
                              setRepoToDelete(repo);
                              setDeleteReason('');
                              setShowDeleteModal(true);
                            }}
                            className="inline-flex items-center gap-1 px-2 py-1.5 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 text-[11px]"
                            title="Permanently delete repository and all related data"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ));
                  })()}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        /* SECTION 4: DRILLDOWN VIEW FOR SELECTED REPOSITORY */
        <div className="space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800">
            <div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setActiveTab('overview')}
                  className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
                >
                  ← Back to General Averages
                </button>
              </div>
              <div className="flex items-center gap-3 mt-1">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <GitBranch className="w-5 h-5 text-indigo-400" />
                  {repoDetail?.repo?.name || 'Repository Drilldown'}
                </h2>
                <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                  repoDetail?.repo?.label_quality === 'verified'
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                }`}>
                  {repoDetail?.repo?.label_quality === 'verified' ? 'Verified Ground Truth' : 'Provisional (Auto-Extracted)'}
                </span>
                {repoDetail?.repo?.is_excluded && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                    Excluded: {repoDetail.repo.exclusion_reason}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Vulnerable Commit: <code className="text-slate-300">{repoDetail?.repo?.pinned_sha}</code> • Clean Commit: <code className="text-slate-300">{repoDetail?.repo?.clean_sha || 'N/A'}</code> • LOC: {repoDetail?.repo?.loc}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {!capabilities.readonly && repoDetail?.repo && (
                <button
                  onClick={() => handleRunBenchmark(repoDetail.repo)}
                  disabled={repoDetail.repo.status === 'running' || runningRepoIds.has(repoDetail.repo.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    repoDetail.repo.status === 'running' || runningRepoIds.has(repoDetail.repo.id)
                      ? 'bg-slate-800 text-slate-500 cursor-not-allowed opacity-75'
                      : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm shadow-indigo-500/20'
                  }`}
                  title={repoDetail.repo.status === 'done' ? 'Re-run full benchmark pipeline' : 'Run automated benchmark pipeline'}
                >
                  {repoDetail.repo.status === 'running' || runningRepoIds.has(repoDetail.repo.id) ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5 animate-spin" />
                      Running...
                    </>
                  ) : repoDetail.repo.status === 'done' ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5" />
                      Re-run Benchmark
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5 fill-current" />
                      Run Benchmark
                    </>
                  )}
                </button>
              )}
              {!capabilities.readonly && (
                <>
                  <button
                    onClick={() => selectedRepoId && handleExportBlindTriage(selectedRepoId)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-300 text-xs font-medium transition"
                  >
                    <EyeOff className="w-3.5 h-3.5 text-indigo-400" />
                    Export Blind Triage
                  </button>
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={triageUploadLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 text-xs font-medium transition"
                  >
                    <Upload className="w-3.5 h-3.5" />
                    Import Verified Labels
                  </button>
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleImportBlindTriage}
                    accept=".json"
                    className="hidden"
                  />
                </>
              )}
              {(() => {
                const rawUrl = (repoDetail?.repo?.url || '').trim();
                const urlMatch = rawUrl.match(/^https:\/\/github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git|\/.*)?$/);
                const nameMatch = (repoDetail?.repo?.name || '').trim().match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)/);
                const owner = urlMatch?.[1] || nameMatch?.[1];
                const repoName = urlMatch?.[2] || nameMatch?.[2];
                const safeGitHubUrl = owner && repoName ? `https://github.com/${owner}/${repoName}` : null;
                return safeGitHubUrl ? (
                  <a
                    href={safeGitHubUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition"
                  >
                    GitHub Source
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                ) : (
                  <span
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-500 text-xs font-medium cursor-not-allowed"
                    title="Invalid or unavailable GitHub repository URL"
                  >
                    GitHub Source
                    <ExternalLink className="w-3.5 h-3.5" />
                  </span>
                );
              })()}
            </div>
          </div>

          {detailLoading ? (
            <div className="space-y-5 animate-pulse" aria-label="Loading repository details">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, idx) => (
                  <div key={idx} className="h-28 rounded-xl bg-slate-900/70 border border-slate-800 p-4 space-y-3">
                    <div className="h-3.5 w-24 rounded bg-slate-800" />
                    <div className="h-6 w-16 rounded bg-slate-800" />
                    <div className="h-3 w-32 rounded bg-slate-800/70" />
                  </div>
                ))}
              </div>
              <div className="h-72 rounded-xl bg-slate-900/70 border border-slate-800 p-5 space-y-3">
                <div className="h-4 w-48 rounded bg-slate-800" />
                {Array.from({ length: 5 }).map((_, idx) => (
                  <div key={idx} className="h-9 w-full rounded bg-slate-800/50" />
                ))}
              </div>
            </div>
          ) : (
            <>
          {/* Stage-Level Timing Breakdown */}
          {repoDetail?.stage_timings && Object.keys(repoDetail.stage_timings).length > 0 && (
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-semibold text-slate-200">
                  <Clock className="w-4 h-4 text-indigo-400" />
                  <span>Stage-Level Timing Breakdown</span>
                </div>
                <span className="text-[11px] text-slate-400">
                  Mode: <span className="font-mono text-indigo-300">{repoDetail.stage_timings.latency_measurement_mode || 'isolated_sequential'}</span> (no concurrent tool contention)
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {repoDetail.stage_timings.clone_or_fetch_s != null && (
                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                    <div className="text-[10px] text-slate-500">Clone / Cache Fetch</div>
                    <div className="font-mono text-slate-200">{Number(repoDetail.stage_timings.clone_or_fetch_s).toFixed(2)}s</div>
                  </div>
                )}
                {repoDetail.stage_timings.filtered_copy_vuln_s != null && (
                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                    <div className="text-[10px] text-slate-500">Filtered Copy (Vuln)</div>
                    <div className="font-mono text-slate-200">{Number(repoDetail.stage_timings.filtered_copy_vuln_s).toFixed(2)}s</div>
                  </div>
                )}
                {repoDetail.stage_timings.filtered_copy_clean_s != null && (
                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                    <div className="text-[10px] text-slate-500">Filtered Copy (Clean)</div>
                    <div className="font-mono text-slate-200">{Number(repoDetail.stage_timings.filtered_copy_clean_s).toFixed(2)}s</div>
                  </div>
                )}
                {repoDetail.stage_timings.evaluator_s != null && (
                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                    <div className="text-[10px] text-slate-500">Evaluator</div>
                    <div className="font-mono text-slate-200">{Number(repoDetail.stage_timings.evaluator_s).toFixed(3)}s</div>
                  </div>
                )}
              </div>
              {repoDetail.stage_timings.tools && Object.keys(repoDetail.stage_timings.tools).length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[11px] border border-slate-800 rounded">
                    <thead className="bg-slate-950 text-slate-400">
                      <tr>
                        <th className="px-3 py-1.5">Tool</th>
                        <th className="px-3 py-1.5">Source</th>
                        <th className="px-3 py-1.5">Vuln (s)</th>
                        <th className="px-3 py-1.5">Clean (s)</th>
                        <th className="px-3 py-1.5">Breakdown</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {Object.entries(repoDetail.stage_timings.tools).map(([tName, tTimings]: [string, any]) => {
                        const parts: string[] = [];
                        if (tTimings.vuln_db_build_s != null) parts.push(`vuln DB: ${Number(tTimings.vuln_db_build_s).toFixed(2)}s`);
                        if (tTimings.vuln_analysis_s != null) parts.push(`vuln analyze: ${Number(tTimings.vuln_analysis_s).toFixed(2)}s`);
                        if (tTimings.clean_db_build_s != null) parts.push(`clean DB: ${Number(tTimings.clean_db_build_s).toFixed(2)}s`);
                        if (tTimings.clean_analysis_s != null) parts.push(`clean analyze: ${Number(tTimings.clean_analysis_s).toFixed(2)}s`);
                        if (tTimings.vuln_container_startup_s != null) parts.push(`vuln startup: ${Number(tTimings.vuln_container_startup_s).toFixed(2)}s`);
                        if (tTimings.vuln_scan_s != null) parts.push(`vuln scan: ${Number(tTimings.vuln_scan_s).toFixed(2)}s`);
                        if (tTimings.clean_container_startup_s != null) parts.push(`clean startup: ${Number(tTimings.clean_container_startup_s).toFixed(2)}s`);
                        if (tTimings.clean_scan_s != null) parts.push(`clean scan: ${Number(tTimings.clean_scan_s).toFixed(2)}s`);
                        return (
                          <tr key={tName} className="bg-slate-900/40">
                            <td className="px-3 py-1.5 font-mono text-slate-200">{tName}</td>
                            <td className="px-3 py-1.5">
                              {tTimings.cached ? (
                                <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/30 font-mono text-[10px]">
                                  cached{tTimings.original_timestamp ? ` (${new Date(tTimings.original_timestamp).toLocaleDateString()})` : ''}
                                </span>
                              ) : (
                                <span className="text-slate-400">fresh scan</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 font-mono text-slate-300">{tTimings.vuln_duration_s != null ? Number(tTimings.vuln_duration_s).toFixed(2) : '-'}</td>
                            <td className="px-3 py-1.5 font-mono text-slate-300">{tTimings.clean_duration_s != null ? Number(tTimings.clean_duration_s).toFixed(2) : '-'}</td>
                            <td className="px-3 py-1.5 font-mono text-slate-400">{parts.length > 0 ? parts.join(' • ') : '-'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Noise Filtering / Ignored Candidates Drawer */}
          {repoDetail?.repo?.ignored_candidates && repoDetail.repo.ignored_candidates.length > 0 && (
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs space-y-2">
              <div className="flex items-center gap-2 font-semibold text-slate-300">
                <Info className="w-4 h-4 text-slate-400" />
                <span>Noise Filtering Transparency ({repoDetail.repo.ignored_candidates.length} candidate diffs excluded)</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-32 overflow-y-auto">
                {repoDetail.repo.ignored_candidates.map((c: any, i: number) => (
                  <div key={i} className="font-mono text-[11px] text-slate-400 bg-slate-950 p-1.5 rounded border border-slate-800/80 truncate">
                    <span className="text-slate-300">{c.file}</span>: <span className="text-slate-500">{c.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Ground Truth Labeled Findings Matrix */}
          <div className="space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-white">Landed Ground-Truth Vulnerabilities</h3>
                <p className="text-xs text-slate-400">
                  Extracted from fix commit diff with automatic noise filtering.
                </p>
              </div>

              <div className="relative w-full sm:w-64">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter file, line, CWE..."
                  value={findingSearch}
                  onChange={(e) => setFindingSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/70 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="px-4 py-3">ID</th>
                    <th className="px-4 py-3">File Location</th>
                    <th className="px-4 py-3">Line</th>
                    <th className="px-4 py-3">CWE Class</th>
                    <th className="px-4 py-3">Severity</th>
                    <th className="px-4 py-3">Description & Notes</th>
                    <th className="px-4 py-3">CodeGuardian</th>
                    <th className="px-4 py-3">Semgrep</th>
                    <th className="px-4 py-3">CodeQL</th>
                    <th className="px-4 py-3">Bandit</th>
                    <th className="px-4 py-3">SonarQube</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 text-slate-300">
                  {((repoDetail?.ground_truth?.labeled_findings || []) as any[])
                    .filter((f) => {
                      const q = findingSearch.toLowerCase();
                      return (
                        !q ||
                        f.file?.toLowerCase().includes(q) ||
                        f.cwe?.toLowerCase().includes(q) ||
                        f.notes?.toLowerCase().includes(q) ||
                        f.id?.toLowerCase().includes(q)
                      );
                    })
                    .map((item, idx) => {
                      const renderToolCell = (toolKey: string) => {
                        const run = (repoDetail?.runs || []).find((r: any) => r.tool === toolKey);
                        if (!run || run.status !== 'completed') {
                          return (
                            <span
                              className="text-[11px] text-slate-500 italic"
                              title={run?.error_message || `${toolKey}: ${run?.status || 'not run'}`}
                            >
                              not run
                            </span>
                          );
                        }
                        const toolFindings = (repoDetail?.findings || []).filter((f: any) => f.tool === toolKey);
                        const match = toolFindings.find(
                          (f: any) =>
                            (f.match_result === 'TP' && f.matched_ground_truth_id === item.id) ||
                            (f.file_path &&
                              item.file &&
                              f.file_path.replace(/\\/g, '/').endsWith(item.file.replace(/\\/g, '/')) &&
                              Math.abs((f.line_start || 0) - (item.line_start || 0)) <= 10)
                        );
                        if (match) {
                          const dist = Math.abs((match.line_start || 0) - (item.line_start || 0));
                          return (
                            <span
                              className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-medium"
                              title={`${match.rule_id || toolKey} (${match.cwe || 'unknown'}) at line ${match.line_start}`}
                            >
                              <Check className="w-3.5 h-3.5" /> Detected (±{dist}L)
                            </span>
                          );
                        }
                        return (
                          <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                            <X className="w-3.5 h-3.5" /> Missed
                          </span>
                        );
                      };
                      return (
                      <tr key={item.id || idx} className="hover:bg-slate-800/40 transition">
                        <td className="px-4 py-3 font-mono text-[11px] text-indigo-400 font-semibold">{item.id}</td>
                        <td className="px-4 py-3 font-mono text-[11px] text-white">{item.file}</td>
                        <td className="px-4 py-3 font-mono text-[11px] text-slate-300">
                          {item.line_start === item.line_end ? item.line_start : `${item.line_start}-${item.line_end}`}
                        </td>
                        <td className="px-4 py-3">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-200 border border-slate-700">
                            {item.cwe}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                              item.severity === 'CRITICAL'
                                ? 'bg-red-500/10 text-red-400 border border-red-500/30'
                                : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                            }`}
                          >
                            {item.severity}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400 max-w-xs truncate">{item.notes || 'Documented flaw'}</td>
                        <td className="px-4 py-3">{renderToolCell('codeguardian')}</td>
                        <td className="px-4 py-3">{renderToolCell('semgrep')}</td>
                        <td className="px-4 py-3">{renderToolCell('codeql')}</td>
                        <td className="px-4 py-3">{renderToolCell('bandit')}</td>
                        <td className="px-4 py-3">{renderToolCell('sonarqube')}</td>
                      </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>
            </>
          )}
        </div>
      )}
        </>
      )}

      {/* ONE-STEP ADD REPOSITORY MODAL */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Plus className="w-5 h-5 text-indigo-400" />
                <h3 className="text-base font-bold text-white">Add Research Benchmark Repository</h3>
              </div>
              <button
                onClick={() => setShowAddModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleAddRepo} className="space-y-4">
              {addError && (
                <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs">
                  {addError}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  GitHub Repository URL
                </label>
                <input
                  type="text"
                  placeholder="https://github.com/psf/requests (or direct commit URL)"
                  value={addUrl}
                  onChange={(e) => handleUrlChange(e.target.value)}
                  required
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
                <p className="text-[11px] text-slate-500 mt-1">
                  Repository URL or direct GitHub commit URL.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  CVE Identifier OR Fix Commit SHA
                </label>
                <input
                  type="text"
                  placeholder="CVE-2018-18074, commit SHA, or NVD / advisory URL"
                  value={addIdentifier}
                  onChange={(e) => handleIdentifierChange(e.target.value)}
                  required
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
                <p className="text-[11px] text-slate-500 mt-1">
                  Accepts CVE-YYYY-NNNN, commit SHA, or NVD / advisory URL.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  CWE Classification (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. CWE-22 (auto-resolved if CVE/GHSA provided)"
                  value={addCwe}
                  onChange={(e) => setAddCwe(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="pt-3 border-t border-slate-800 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isAdding}
                  className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium flex items-center gap-1.5 disabled:opacity-50"
                >
                  {isAdding && <RotateCw className="w-3.5 h-3.5 animate-spin" />}
                  {isAdding ? 'Queueing Pipeline...' : 'Start Automated Pipeline'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EXCLUDE REPOSITORY MODAL */}
      {showExcludeModal && repoToExclude && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-center gap-2 text-rose-400">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <h3 className="text-base font-bold text-white">Exclude from General Averages</h3>
            </div>
            <p className="text-xs text-slate-300">
              Excluding <strong>{repoToExclude.name}</strong> removes its findings from macro-averages. Scientific integrity requires a mandatory written reason (shown in methodology).
            </p>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Mandatory Written Reason
              </label>
              <textarea
                rows={3}
                placeholder="e.g. Broad squash commit containing major refactor unrelated to vulnerability..."
                value={excludeReason}
                onChange={(e) => setExcludeReason(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-rose-500"
              />
            </div>

            <div className="pt-2 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowExcludeModal(false);
                  setRepoToExclude(null);
                }}
                className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleExcludeSubmit}
                disabled={isExcluding}
                className="px-4 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium"
              >
                {isExcluding ? 'Excluding...' : 'Confirm Exclusion'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DELETE REPOSITORY MODAL */}
      {showDeleteModal && repoToDelete && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-center gap-2 text-rose-400">
              <Trash2 className="w-5 h-5 flex-shrink-0" />
              <h3 className="text-base font-bold text-white">Permanently Delete Repository</h3>
            </div>
            <p className="text-xs text-slate-300">
              Deleting <strong>{repoToDelete.name}</strong> (<span className="font-mono text-[11px]">{repoToDelete.id}</span>) will permanently remove:
            </p>
            <ul className="text-xs text-slate-400 list-disc list-inside space-y-1">
              <li>The repository record and ignored candidates</li>
              <li>All benchmark runs, findings, and metrics</li>
              <li>The ground-truth manifest and cached clone directories on disk</li>
            </ul>

            {(repoToDelete.has_completed_run || (repoToDelete.completed_runs_count ?? 0) > 0) && (
              <div className="space-y-2 pt-1">
                <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-300">
                  This repository has {repoToDelete.completed_runs_count} completed run(s). A written reason is required and will be logged in a permanent deletion audit record.
                </div>
                <label className="block text-xs font-semibold text-slate-300">
                  Mandatory Written Reason
                </label>
                <textarea
                  rows={3}
                  placeholder="e.g. Removing obsolete pre-refactoring baseline run..."
                  value={deleteReason}
                  onChange={(e) => setDeleteReason(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-rose-500"
                />
              </div>
            )}

            <div className="pt-2 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowDeleteModal(false);
                  setRepoToDelete(null);
                  setDeleteReason('');
                }}
                className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteSubmit}
                disabled={
                  isDeleting ||
                  (Boolean(repoToDelete.has_completed_run || (repoToDelete.completed_runs_count ?? 0) > 0) &&
                    deleteReason.trim().length < 5)
                }
                className="px-4 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium"
              >
                {isDeleting ? 'Deleting...' : 'Confirm Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* METHODOLOGY MODAL */}
      {showMethodologyModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-indigo-400" />
                <h3 className="text-lg font-bold text-white">Benchmark Methodology & Mathematical Formulas</h3>
              </div>
              <button
                onClick={() => setShowMethodologyModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 text-xs text-slate-300 leading-relaxed">
              <div>
                <h4 className="font-semibold text-white text-sm mb-1">1. Automatic CVE Fix Commit Extraction</h4>
                <p>
                  Vulnerable candidate lines are automatically extracted from the parent commit ($N-1$) corresponding to lines changed in source files by the security fix commit ($N$). Non-code changes (tests, docs, build configs, lockfiles, comments, imports, whitespace) are strictly filtered out and recorded in an ignored candidate log.
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-white text-sm mb-1">2. Provisional vs Verified Ground Truth</h4>
                <p>
                  Newly ingested CVE repositories are labeled <strong>Provisional</strong> by default. For provisional repositories, False Positive Rate (FPR) is an <strong>upper bound</strong> because pre-existing vulnerabilities in the clean commit will count as false alarms. Repositories can be upgraded to <strong>Verified</strong> via blinded human triage.
                </p>
              </div>

              <div>
                <h4 className="font-semibold text-white text-sm mb-1">3. The Six Metric Formulas</h4>
                <div className="space-y-2 bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-[11px]">
                  <p><strong>Precision:</strong> TP / (TP + FP) over findings on vulnerable snapshot.</p>
                  <p><strong>Recall:</strong> TP / (TP + FN) against labeled ground truth.</p>
                  <p><strong>False Positive Rate:</strong> Clean-FP / kLOC reported on post-fix snapshot.</p>
                  <p><strong>Localization Accuracy:</strong> Share of TPs where reported line is within ±3 lines.</p>
                  <p><strong>Classification Accuracy:</strong> Share of TPs matching labeled CWE via equivalence map.</p>
                  <p><strong>Scan Latency:</strong> Seconds per 1,000 LOC on identical warm hardware.</p>
                </div>
              </div>

              <div>
                <h4 className="font-semibold text-white text-sm mb-1">4. Competitor Tool Matrix</h4>
                <ul className="list-disc list-inside space-y-1 text-slate-400">
                  <li><strong>Semgrep OSS:</strong> Version 1.74.0 with default auto ruleset.</li>
                  <li><strong>GitHub CodeQL:</strong> Version 2.16.2 (latency includes database creation).</li>
                  <li><strong>SonarQube Community:</strong> Version 10.4 Community Edition.</li>
                  <li><strong>Bandit:</strong> Version 1.8.6 (Python reference line only).</li>
                </ul>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800 flex justify-end">
              <button
                onClick={() => setShowMethodologyModal(false)}
                className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default EvalDashboard;
