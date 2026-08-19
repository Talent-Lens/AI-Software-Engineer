import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  AlertTriangle, 
  XCircle, 
  CheckCircle2, 
  HelpCircle, 
  RefreshCw, 
  Download, 
  Search, 
  Filter, 
  Layers, 
  ExternalLink, 
  ChevronDown, 
  ChevronUp, 
  Lock, 
  Key, 
  Database, 
  Globe, 
  PackageCheck, 
  FileCode, 
  Sparkles,
  Info,
  SlidersHorizontal,
  Check
} from 'lucide-react';
import { LaunchChecklistReport, ChecklistItem, ChecklistStatus } from '../types';
import { fetchLaunchChecklist } from '../services/api';

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  'Secrets & Credentials': Key,
  'Access Control': Lock,
  'Data Protection': Database,
  'Input Validation': FileCode,
  'Infrastructure & Headers': Globe,
  'Dependencies': PackageCheck,
};

const CATEGORIES = [
  'All Categories',
  'Secrets & Credentials',
  'Access Control',
  'Data Protection',
  'Input Validation',
  'Infrastructure & Headers',
  'Dependencies',
];

export const LaunchChecklist: React.FC = () => {
  const [report, setReport] = useState<LaunchChecklistReport | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('All Categories');
  const [selectedStatus, setSelectedStatus] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadAudit = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchLaunchChecklist();
      setReport(data);
      // Expand all failed and manual review items by default for immediate visibility
      const defaultExpanded: Record<string, boolean> = {};
      if (data?.items) {
        data.items.forEach((item: ChecklistItem) => {
          if (item.status === 'FAIL' || item.status === 'MANUAL_REVIEW') {
            defaultExpanded[item.id] = true;
          }
        });
      }
      setExpandedItems(defaultExpanded);
    } catch (err: any) {
      console.error('Launch checklist fetch failed:', err);
      setError(err?.message || 'Failed to execute pre-launch security audit.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAudit();
  }, []);

  const toggleExpand = (id: string) => {
    setExpandedItems(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const expandAll = () => {
    if (!report?.items) return;
    const all: Record<string, boolean> = {};
    report.items.forEach(i => { all[i.id] = true; });
    setExpandedItems(all);
  };

  const collapseAll = () => {
    setExpandedItems({});
  };

  const handleExportMarkdown = () => {
    if (!report) return;
    let md = `# CodeGuardian Pre-Launch Security Checklist Audit\n\n`;
    md += `**Execution Date:** ${report.timestamp}\n`;
    md += `**Readiness Score:** ${report.readinessPercentage}% (${report.passedCount}/${report.totalChecks} Passed)\n`;
    md += `**Launch Grade:** ${report.grade} | **Status:** ${report.launchStatus}\n\n`;
    md += `## Summary\n${report.summary}\n\n`;
    md += `## Detailed Checks Breakdown\n\n`;

    report.items.forEach(item => {
      const statusIcon = item.status === 'PASS' ? '✅ PASS' : item.status === 'FAIL' ? '❌ FAIL' : item.status === 'MANUAL_REVIEW' ? '🔍 MANUAL REVIEW' : '⚠️ N/A';
      md += `### [${item.id}] ${item.title} — ${statusIcon}\n`;
      md += `- **Category:** ${item.category}\n`;
      md += `- **Severity:** ${item.severity}\n`;
      md += `- **Finding:** ${item.explanation}\n`;
      md += `- **Remediation:** ${item.remediation}\n`;
      if (item.filePath) md += `- **File Citation:** \`${item.filePath}\`${item.lineNumber ? ` (Line ${item.lineNumber})` : ''}\n`;
      if (item.snippet) md += `- **Code Snippet:** \`${item.snippet}\`\n`;
      if (item.manualReviewReason) md += `- **Manual Review Reason:** ${item.manualReviewReason}\n`;
      md += `\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pre_launch_security_audit_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const filteredItems = (report?.items || []).filter(item => {
    const matchesCategory = selectedCategory === 'All Categories' || item.category === selectedCategory;
    const matchesStatus = selectedStatus === 'ALL' || item.status === selectedStatus;
    const matchesSearch = 
      item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.explanation.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.category.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesStatus && matchesSearch;
  });

  // Group filtered items by category for scannable structured layout
  const groupedItems = CATEGORIES.slice(1).map(category => {
    const itemsInCategory = filteredItems.filter(i => i.category === category);
    return {
      category,
      items: itemsInCategory,
      totalInCategory: (report?.items || []).filter(i => i.category === category).length,
      passedInCategory: (report?.items || []).filter(i => i.category === category && i.status === 'PASS').length,
    };
  }).filter(group => group.items.length > 0);

  const getStatusBadge = (status: ChecklistStatus, severity: string) => {
    switch (status) {
      case 'PASS':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-950/70 text-emerald-300 border border-emerald-500/30">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span>Pass</span>
          </span>
        );
      case 'FAIL':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-rose-950/70 text-rose-300 border border-rose-500/40 animate-pulse">
            <XCircle className="w-3.5 h-3.5 text-rose-400" />
            <span>Fail ({severity})</span>
          </span>
        );
      case 'MANUAL_REVIEW':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-950/70 text-amber-300 border border-amber-500/30">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <span>Manual Review</span>
          </span>
        );
      case 'NOT_APPLICABLE':
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-[#1e202e] text-[#94a3b8] border border-[#2b2f45]">
            <HelpCircle className="w-3.5 h-3.5 text-[#64748b]" />
            <span>N/A</span>
          </span>
        );
    }
  };

  const getLaunchStatusPill = (status: string, grade: string) => {
    if (status === 'LAUNCH_READY') {
      return (
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-emerald-300">
          <Sparkles className="w-4 h-4 text-emerald-400" />
          <span className="text-xs font-bold tracking-wide">READY FOR LAUNCH</span>
        </div>
      );
    }
    if (status === 'NEEDS_REVIEW') {
      return (
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-amber-950/60 border border-amber-500/40 text-amber-300">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-xs font-bold tracking-wide">REVIEW REQUIRED</span>
        </div>
      );
    }
    return (
      <div className="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-300">
        <XCircle className="w-4 h-4 text-rose-400" />
        <span className="text-xs font-bold tracking-wide">BLOCK DEPLOYMENT</span>
      </div>
    );
  };

  return (
    <div className="flex-1 bg-[#0c0d14] text-[#cbd5e1] flex flex-col h-full overflow-y-auto select-text p-4 md:p-6 space-y-6">
      
      {/* Top Hero Banner & Launch Readiness Card */}
      <div className="bg-[#151722] p-5 md:p-6 rounded-3xl border border-[#232638] shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-600/5 rounded-full blur-3xl pointer-events-none" />
        
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative z-10">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-indigo-600/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400 flex-shrink-0 shadow-inner">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center space-x-3">
                  <h1 className="text-lg md:text-xl font-bold text-white tracking-tight">
                    Pre-Launch Security Checklist
                  </h1>
                  {report && getLaunchStatusPill(report.launchStatus, report.grade)}
                </div>
                <p className="text-xs text-[#94a3b8] mt-0.5">
                  Automated 20-Point Production Readiness & Vulnerability Audit
                </p>
              </div>
            </div>
            {report && (
              <p className="text-xs text-[#cbd5e1] max-w-2xl pt-1 leading-relaxed">
                {report.summary}
              </p>
            )}
          </div>

          {/* Readiness Score & Actions */}
          <div className="flex flex-wrap items-center gap-4 self-start lg:self-center">
            {report && (
              <div className="flex items-center space-x-3 bg-[#11131c] px-4 py-2.5 rounded-2xl border border-[#232638]">
                <div className="text-center">
                  <div className="text-[10px] text-[#94a3b8] font-medium uppercase tracking-wider">Readiness</div>
                  <div className="text-lg font-extrabold text-white">
                    {report.readinessPercentage.toFixed(0)}%
                  </div>
                </div>
                <div className="h-7 w-[1px] bg-[#232638]" />
                <div className="text-center">
                  <div className="text-[10px] text-[#94a3b8] font-medium uppercase tracking-wider">Grade</div>
                  <div className={`text-lg font-extrabold ${report.grade.startsWith('A') ? 'text-emerald-400' : report.grade.startsWith('B') ? 'text-indigo-400' : 'text-rose-400'}`}>
                    {report.grade}
                  </div>
                </div>
                <div className="h-7 w-[1px] bg-[#232638]" />
                <div className="text-center">
                  <div className="text-[10px] text-[#94a3b8] font-medium uppercase tracking-wider">Passed</div>
                  <div className="text-lg font-extrabold text-emerald-400">
                    {report.passedCount}/{report.totalChecks}
                  </div>
                </div>
              </div>
            )}

            <div className="flex items-center space-x-2">
              <button
                onClick={loadAudit}
                disabled={isLoading}
                className="flex items-center space-x-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white text-xs font-semibold rounded-xl shadow-lg shadow-indigo-950/40 transition-all cursor-pointer disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                <span>{isLoading ? 'Auditing Codebase...' : 'Re-Run Live Audit'}</span>
              </button>

              <button
                onClick={handleExportMarkdown}
                disabled={!report}
                className="flex items-center space-x-1.5 px-3 py-2.5 bg-[#181a26] hover:bg-[#202334] border border-[#2b2f45] text-white text-xs font-medium rounded-xl transition cursor-pointer disabled:opacity-50"
                title="Export audit report as Markdown"
              >
                <Download className="w-3.5 h-3.5 text-indigo-300" />
                <span className="hidden sm:inline">Export Report</span>
              </button>
            </div>
          </div>
        </div>

        {/* 4 Summary Stat Mini Cards */}
        {report && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-5 border-t border-[#232638]/70">
            <div className="bg-[#11131c]/60 p-3 rounded-2xl border border-emerald-500/20 flex items-center justify-between">
              <div>
                <span className="text-[11px] text-[#94a3b8]">Passed Checks</span>
                <div className="text-base font-bold text-emerald-400 mt-0.5">{report.passedCount} of 20</div>
              </div>
              <CheckCircle2 className="w-5 h-5 text-emerald-500/50" />
            </div>

            <div className="bg-[#11131c]/60 p-3 rounded-2xl border border-rose-500/20 flex items-center justify-between">
              <div>
                <span className="text-[11px] text-[#94a3b8]">Critical / High Fails</span>
                <div className="text-base font-bold text-rose-400 mt-0.5">{report.failedCount}</div>
              </div>
              <XCircle className="w-5 h-5 text-rose-500/50" />
            </div>

            <div className="bg-[#11131c]/60 p-3 rounded-2xl border border-amber-500/20 flex items-center justify-between">
              <div>
                <span className="text-[11px] text-[#94a3b8]">Manual Review</span>
                <div className="text-base font-bold text-amber-400 mt-0.5">{report.manualReviewCount}</div>
              </div>
              <AlertTriangle className="w-5 h-5 text-amber-500/50" />
            </div>

            <div className="bg-[#11131c]/60 p-3 rounded-2xl border border-[#232638] flex items-center justify-between">
              <div>
                <span className="text-[11px] text-[#94a3b8]">Not Applicable</span>
                <div className="text-base font-bold text-[#94a3b8] mt-0.5">{report.notApplicableCount}</div>
              </div>
              <HelpCircle className="w-5 h-5 text-[#64748b]/50" />
            </div>
          </div>
        )}
      </div>

      {/* Filter and Search Controls */}
      <div className="bg-[#151722] p-4 rounded-2xl border border-[#232638] flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
        
        {/* Category Filter Pills */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 md:pb-0 scrollbar-none">
          {CATEGORIES.map(cat => {
            const isSelected = selectedCategory === cat;
            const Icon = cat === 'All Categories' ? SlidersHorizontal : CATEGORY_ICONS[cat] || ShieldCheck;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap transition cursor-pointer ${
                  isSelected
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-[#11131c] text-[#94a3b8] hover:text-white hover:bg-[#1b1e2c] border border-[#232638]'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{cat}</span>
              </button>
            );
          })}
        </div>

        {/* Status Dropdown & Search Bar */}
        <div className="flex items-center space-x-2.5">
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="bg-[#11131c] border border-[#2b2f45] rounded-xl px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
          >
            <option value="ALL">All Statuses</option>
            <option value="FAIL">Failed Only (❌)</option>
            <option value="MANUAL_REVIEW">Manual Review (🔍)</option>
            <option value="PASS">Passed (✅)</option>
            <option value="NOT_APPLICABLE">Not Applicable (⚠️)</option>
          </select>

          <div className="relative w-full sm:w-60">
            <Search className="w-3.5 h-3.5 text-[#64748b] absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search 20 checks..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl pl-9 pr-3 py-1.5 text-xs text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 transition"
            />
          </div>

          <div className="hidden lg:flex items-center space-x-1 border-l border-[#232638] pl-2.5">
            <button
              onClick={expandAll}
              className="px-2 py-1 text-[11px] text-[#94a3b8] hover:text-white transition cursor-pointer"
            >
              Expand All
            </button>
            <button
              onClick={collapseAll}
              className="px-2 py-1 text-[11px] text-[#94a3b8] hover:text-white transition cursor-pointer"
            >
              Collapse All
            </button>
          </div>
        </div>

      </div>

      {/* Loading Skeleton */}
      {isLoading && !report && (
        <div className="space-y-4 animate-pulse">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-[#151722] p-5 rounded-3xl border border-[#232638] h-32" />
          ))}
        </div>
      )}

      {/* Error Alert Banner */}
      {error && (
        <div className="bg-rose-950/40 border border-rose-500/40 p-4 rounded-2xl flex items-center justify-between text-xs text-rose-200">
          <div className="flex items-center space-x-2.5">
            <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>Audit execution error: {error}</span>
          </div>
          <button
            onClick={loadAudit}
            className="px-3 py-1 bg-rose-600/30 hover:bg-rose-600/50 border border-rose-500/40 rounded-lg text-white font-medium cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Main Scannable Grouped Checklist */}
      <div className="space-y-6">
        {groupedItems.map(group => {
          const CategoryIcon = CATEGORY_ICONS[group.category] || ShieldCheck;
          return (
            <div key={group.category} className="bg-[#151722] rounded-3xl border border-[#232638] overflow-hidden shadow-sm">
              
              {/* Category Header Bar */}
              <div className="bg-[#11131c] px-5 py-3.5 border-b border-[#232638] flex items-center justify-between">
                <div className="flex items-center space-x-2.5">
                  <div className="w-7 h-7 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                    <CategoryIcon className="w-4 h-4" />
                  </div>
                  <h2 className="text-xs font-bold text-white uppercase tracking-wider">
                    {group.category}
                  </h2>
                </div>
                <div className="flex items-center space-x-2 text-xs text-[#94a3b8]">
                  <span className="text-emerald-400 font-semibold">{group.passedInCategory}</span>
                  <span>/</span>
                  <span>{group.totalInCategory} Passed</span>
                </div>
              </div>

              {/* Checks List */}
              <div className="divide-y divide-[#1f2233]">
                {group.items.map(item => {
                  const isExpanded = !!expandedItems[item.id];
                  return (
                    <div 
                      key={item.id}
                      className={`transition-colors ${
                        item.status === 'FAIL' 
                          ? 'bg-rose-950/10 hover:bg-rose-950/20' 
                          : item.status === 'MANUAL_REVIEW'
                          ? 'bg-amber-950/5 hover:bg-amber-950/10'
                          : 'hover:bg-[#181a26]'
                      }`}
                    >
                      {/* Check Summary Row */}
                      <div 
                        onClick={() => toggleExpand(item.id)}
                        className="p-4 flex items-start sm:items-center justify-between gap-4 cursor-pointer select-none"
                      >
                        <div className="flex items-start sm:items-center space-x-3.5 flex-1 min-w-0">
                          <span className="text-[11px] font-mono font-bold text-[#64748b] bg-[#11131c] px-2 py-0.5 rounded border border-[#232638] flex-shrink-0">
                            {item.id}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-bold text-white tracking-tight">
                                {item.title}
                              </span>
                              {getStatusBadge(item.status, item.severity)}
                              {item.filePath && (
                                <span className="text-[11px] font-mono text-[#94a3b8] bg-[#11131c] px-2 py-0.5 rounded border border-[#232638] truncate max-w-xs">
                                  {item.filePath}{item.lineNumber ? `:${item.lineNumber}` : ''}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-[#94a3b8] mt-1 leading-relaxed line-clamp-1 sm:line-clamp-none">
                              {item.explanation}
                            </p>
                          </div>
                        </div>

                        <button 
                          className="text-[#64748b] hover:text-white p-1 rounded-lg transition flex-shrink-0"
                          title="Toggle details"
                        >
                          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                        </button>
                      </div>

                      {/* Expanded Remediation & Code Detail Drawer */}
                      {isExpanded && (
                        <div className="px-5 pb-4 pt-1 text-xs space-y-3 bg-[#11131c]/60 border-t border-[#1f2233] animate-fadeIn">
                          
                          {/* Remediation Guidance Box */}
                          <div className="p-3 rounded-xl bg-indigo-950/30 border border-indigo-500/20 text-indigo-200 flex items-start space-x-2.5">
                            <Info className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
                            <div className="space-y-1">
                              <span className="font-semibold text-white">Recommended Remediation:</span>
                              <p className="text-[#cbd5e1] leading-relaxed">{item.remediation}</p>
                            </div>
                          </div>

                          {/* Code Snippet Citation */}
                          {item.snippet && (
                            <div className="space-y-1.5">
                              <span className="text-[11px] font-semibold text-[#94a3b8] uppercase tracking-wider">
                                Code Snippet Finding:
                              </span>
                              <pre className="p-3 bg-[#0a0a0f] rounded-xl border border-rose-500/30 font-mono text-xs text-rose-300 overflow-x-auto whitespace-pre-wrap">
                                <code>{item.snippet}</code>
                              </pre>
                            </div>
                          )}

                          {/* Manual Review Context Notice */}
                          {item.manualReviewReason && (
                            <div className="p-3 rounded-xl bg-amber-950/20 border border-amber-500/20 text-amber-200 flex items-start space-x-2.5">
                              <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                              <div>
                                <span className="font-semibold text-white">Why Manual Review is Required:</span>
                                <p className="text-[#e2e8f0] mt-0.5 leading-relaxed">{item.manualReviewReason}</p>
                              </div>
                            </div>
                          )}

                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

            </div>
          );
        })}

        {filteredItems.length === 0 && report && (
          <div className="bg-[#151722] p-12 rounded-3xl border border-[#232638] text-center space-y-3">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto" />
            <h3 className="text-sm font-bold text-white">No Matching Checks</h3>
            <p className="text-xs text-[#94a3b8]">
              No checks found matching your current search query or filter criteria.
            </p>
          </div>
        )}
      </div>

    </div>
  );
};
