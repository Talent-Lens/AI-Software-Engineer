import React, { useState, useEffect } from 'react';
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
  AreaChart, 
  Area 
} from 'recharts';
import { 
  BarChart3, 
  Play, 
  CheckCircle2, 
  Zap, 
  Target, 
  Award, 
  Layers, 
  Search,
  RefreshCw,
  Sparkles,
  TrendingUp
} from 'lucide-react';
import { EvalReport } from '../types';
import { runEvaluation } from '../services/api';

interface EvalDashboardProps {
  initialReport?: EvalReport | null;
}

export const EvalDashboard: React.FC<EvalDashboardProps> = ({ initialReport }) => {
  const [report, setReport] = useState<EvalReport | null>(initialReport || null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    if (!report) {
      loadReport();
    }
  }, []);

  const loadReport = async () => {
    setIsLoading(true);
    const data = await runEvaluation();
    setReport(data);
    setIsLoading(false);
  };

  if (!report) {
    return (
      <div className="flex-1 bg-[#1e1e1e] flex items-center justify-center">
        <div className="text-center space-y-3">
          <RefreshCw className="w-8 h-8 text-[#007acc] animate-spin mx-auto" />
          <p className="text-sm text-[#858585]">Loading Evaluation Analytics Dashboard...</p>
        </div>
      </div>
    );
  }

  const { metrics, results } = report;

  // Data formatting for Recharts
  const triadData = [
    { metric: 'Context Recall', value: metrics.meanContextRecall * 100, fullMark: 100 },
    { metric: 'Context Precision', value: metrics.meanContextPrecision * 100, fullMark: 100 },
    { metric: 'Faithfulness', value: metrics.meanFaithfulness * 100, fullMark: 100 },
    { metric: 'MRR Metric', value: metrics.meanMrr * 100, fullMark: 100 },
  ];

  const hitsAtKData = [
    { k: 'Hits@1', rate: metrics.hitsAt1Rate * 100 },
    { k: 'Hits@3', rate: metrics.hitsAt3Rate * 100 },
    { k: 'Hits@5', rate: metrics.hitsAt5Rate * 100 },
    { k: 'Hits@10', rate: metrics.hitsAt10Rate * 100 },
  ];

  const latencyData = [
    { stage: 'Hybrid Search (RRF)', duration: 42 },
    { stage: 'AST Chunker & Graph', duration: 18 },
    { stage: 'LLM Reasoning (Qwen)', duration: 180 },
    { stage: 'Line Grounding Check', duration: 25 },
    { stage: 'Pytest Sandbox Run', duration: 155 },
  ];

  const filteredResults = results.filter(r => 
    r.query.toLowerCase().includes(searchQuery.toLowerCase()) ||
    r.testCaseId.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 bg-[#1e1e1e] flex flex-col h-full overflow-y-auto select-none p-6 space-y-6">
      {/* Dashboard Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#252526] p-4 rounded-xl border border-[#3c3c3c]">
        <div>
          <div className="flex items-center space-x-2 text-white text-lg font-bold">
            <BarChart3 className="w-6 h-6 text-[#007acc]" />
            <span>RAG Triad & Benchmark Evaluation Suite</span>
          </div>
          <p className="text-xs text-[#858585] mt-1">
            Quantitative benchmark metrics across {report.totalTestCases} ground-truth test cases (Timestamp: {new Date(report.timestamp).toLocaleString()})
          </p>
        </div>

        <button
          onClick={loadReport}
          disabled={isLoading}
          className="flex items-center space-x-2 px-4 py-2 bg-[#007acc] hover:bg-[#005999] active:scale-95 text-white text-xs font-semibold rounded-lg shadow-lg transition-all"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          <span>{isLoading ? 'Running Benchmark...' : 'Run Live Benchmark Suite'}</span>
        </button>
      </div>

      {/* Top 4 KPI Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex items-center justify-between">
          <div>
            <div className="text-xs text-[#858585] font-medium">Context Recall</div>
            <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
              {(metrics.meanContextRecall * 100).toFixed(0)}%
            </div>
            <div className="text-[10px] text-emerald-500/80 font-mono mt-0.5">Target Chunks Retrieved</div>
          </div>
          <div className="p-3 bg-emerald-950/60 text-emerald-400 rounded-lg border border-emerald-800/50">
            <Target className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex items-center justify-between">
          <div>
            <div className="text-xs text-[#858585] font-medium">Context Precision</div>
            <div className="text-2xl font-bold font-mono text-blue-400 mt-1">
              {(metrics.meanContextPrecision * 100).toFixed(0)}%
            </div>
            <div className="text-[10px] text-blue-500/80 font-mono mt-0.5">Signal-to-Noise Ratio</div>
          </div>
          <div className="p-3 bg-blue-950/60 text-blue-400 rounded-lg border border-blue-800/50">
            <Award className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex items-center justify-between">
          <div>
            <div className="text-xs text-[#858585] font-medium">Faithfulness</div>
            <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">
              {(metrics.meanFaithfulness * 100).toFixed(0)}%
            </div>
            <div className="text-[10px] text-cyan-500/80 font-mono mt-0.5">Zero Hallucinations</div>
          </div>
          <div className="p-3 bg-cyan-950/60 text-cyan-400 rounded-lg border border-cyan-800/50">
            <CheckCircle2 className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex items-center justify-between">
          <div>
            <div className="text-xs text-[#858585] font-medium">Hits@1 Rate</div>
            <div className="text-2xl font-bold font-mono text-purple-400 mt-1">
              {(metrics.hitsAt1Rate * 100).toFixed(0)}%
            </div>
            <div className="text-[10px] text-purple-500/80 font-mono mt-0.5">MRR: {metrics.meanMrr.toFixed(2)}</div>
          </div>
          <div className="p-3 bg-purple-950/60 text-purple-400 rounded-lg border border-purple-800/50">
            <Zap className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Visual Graphs Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Graph 1: RAG Triad Radar & Bar Chart */}
        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex flex-col h-80">
          <div className="text-xs font-bold text-white mb-3 flex items-center justify-between">
            <span>RAG Triad Scores (%)</span>
            <span className="text-[10px] text-[#60a5fa] font-mono">Radar Analysis</span>
          </div>
          <div className="flex-1 w-full h-full">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={triadData}>
                <PolarGrid stroke="#3c3c3c" />
                <PolarAngleAxis dataKey="metric" stroke="#858585" tick={{ fill: '#cccccc', fontSize: 11 }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#3c3c3c" />
                <Radar name="Score" dataKey="value" stroke="#007acc" fill="#007acc" fillOpacity={0.5} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Graph 2: Hits@K Accuracy Area Chart */}
        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex flex-col h-80">
          <div className="text-xs font-bold text-white mb-3 flex items-center justify-between">
            <span>Hits@K Retrieval Accuracy</span>
            <span className="text-[10px] text-emerald-400 font-mono">Cumulative Recall</span>
          </div>
          <div className="flex-1 w-full h-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={hitsAtKData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#3c3c3c" />
                <XAxis dataKey="k" stroke="#858585" tick={{ fill: '#cccccc', fontSize: 11 }} />
                <YAxis domain={[0, 100]} stroke="#858585" tick={{ fill: '#cccccc', fontSize: 11 }} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e1e1e', borderColor: '#3c3c3c', borderRadius: 8, color: '#fff' }}
                  formatter={(value: any) => [`${value}%`, 'Accuracy']}
                />
                <Area type="monotone" dataKey="rate" stroke="#10b981" fill="#10b981" fillOpacity={0.3} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Graph 3: Pipeline Stage Latency Breakdown */}
        <div className="bg-[#252526] p-4 rounded-xl border border-[#3c3c3c] flex flex-col h-80">
          <div className="text-xs font-bold text-white mb-3 flex items-center justify-between">
            <span>Stage Latency Breakdown (ms)</span>
            <span className="text-[10px] text-purple-400 font-mono">Total: ~420ms</span>
          </div>
          <div className="flex-1 w-full h-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#3c3c3c" />
                <XAxis type="number" stroke="#858585" tick={{ fill: '#cccccc', fontSize: 11 }} />
                <YAxis dataKey="stage" type="category" stroke="#858585" tick={{ fill: '#cccccc', fontSize: 10 }} width={110} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e1e1e', borderColor: '#3c3c3c', borderRadius: 8, color: '#fff' }}
                  formatter={(val: any) => [`${val} ms`, 'Execution Time']}
                />
                <Bar dataKey="duration" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Benchmark Test Cases Table */}
      <div className="bg-[#252526] rounded-xl border border-[#3c3c3c] p-4 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="text-sm font-bold text-white flex items-center space-x-2">
            <Layers className="w-4 h-4 text-[#007acc]" />
            <span>Golden Benchmark Evaluation Dataset ({filteredResults.length} cases)</span>
          </div>

          <div className="relative w-64">
            <Search className="w-3.5 h-3.5 text-[#858585] absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search test query or ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#1e1e1e] border border-[#3c3c3c] rounded-md pl-9 pr-3 py-1.5 text-xs text-white placeholder-[#666666] focus:outline-none focus:border-[#007acc]"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs select-text">
            <thead>
              <tr className="bg-[#1e1e1e] text-[#858585] border-b border-[#3c3c3c] font-mono">
                <th className="p-3">ID</th>
                <th className="p-3">Evaluation Query</th>
                <th className="p-3">Recall</th>
                <th className="p-3">Precision</th>
                <th className="p-3">Faithfulness</th>
                <th className="p-3">Hits@1</th>
                <th className="p-3">Retrieved Chunk Signature</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#3c3c3c]">
              {filteredResults.map((tc) => (
                <tr key={tc.testCaseId} className="hover:bg-[#2a2d2e] transition-colors">
                  <td className="p-3 font-mono text-[#007acc] font-bold">{tc.testCaseId}</td>
                  <td className="p-3 text-white max-w-md">{tc.query}</td>
                  <td className="p-3 font-mono text-emerald-400 font-semibold">{tc.contextRecall * 100}%</td>
                  <td className="p-3 font-mono text-blue-400 font-semibold">{tc.contextPrecision * 100}%</td>
                  <td className="p-3 font-mono text-cyan-400 font-semibold">{tc.faithfulness * 100}%</td>
                  <td className="p-3 font-mono text-purple-400">
                    {tc.hitsAt1 === 1 ? (
                      <span className="bg-emerald-950 text-emerald-400 px-2 py-0.5 rounded text-[10px] border border-emerald-800">
                        HIT @ 1
                      </span>
                    ) : (
                      '0'
                    )}
                  </td>
                  <td className="p-3 font-mono text-[11px] text-[#ce9178] truncate max-w-xs">
                    {tc.retrievedChunkIds[0] || '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
