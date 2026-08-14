import React, { useState } from 'react';
import { 
  GitFork, 
  Play, 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  FileJson, 
  Terminal, 
  Database, 
  Bug, 
  ShieldCheck, 
  Code2, 
  TestTube2, 
  FileCheck, 
  Cpu, 
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Sparkles,
  ArrowRight,
  Info,
  HelpCircle,
  Check,
  Activity,
  Layers
} from 'lucide-react';
import { GraphNode, PipelineExecutionState } from '../types';

interface LangGraphCanvasProps {
  pipelineState: PipelineExecutionState;
  onRunPipeline: () => void;
}

interface NodePos {
  x: number;
  y: number;
}

// Optimized visual DAG node positions for ultra-clean graph flow
const NODE_POSITIONS: Record<string, NodePos> = {
  retrieval: { x: 60, y: 210 },
  detect: { x: 340, y: 110 },
  security_audit: { x: 340, y: 310 },
  syntax_check: { x: 640, y: 110 },
  line_verifier: { x: 640, y: 310 },
  test_generator: { x: 940, y: 210 },
  doc_verifier: { x: 1210, y: 210 },
};

const DAG_CONNECTIONS = [
  { from: 'retrieval', to: 'detect', label: 'AST Chunks' },
  { from: 'retrieval', to: 'security_audit', label: 'Security Chunks' },
  { from: 'detect', to: 'syntax_check', label: 'Proposed Fix' },
  { from: 'security_audit', to: 'line_verifier', label: 'Citations' },
  { from: 'syntax_check', to: 'test_generator', label: 'Valid Code' },
  { from: 'line_verifier', to: 'test_generator', label: 'Verified Lines' },
  { from: 'test_generator', to: 'doc_verifier', label: 'Passing Tests' },
];

export const LangGraphCanvas: React.FC<LangGraphCanvasProps> = ({
  pipelineState,
  onRunPipeline,
}) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string>('detect');
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [inspectorTab, setInspectorTab] = useState<'summary' | 'json' | 'logs'>('summary');

  const nodeIcons: Record<string, any> = {
    retrieval: Database,
    detect: Bug,
    security_audit: ShieldCheck,
    syntax_check: Code2,
    line_verifier: FileCheck,
    test_generator: TestTube2,
    doc_verifier: FileJson,
  };

  const plainEnglishDescriptions: Record<string, { whatItDoes: string; whyItMatters: string }> = {
    retrieval: {
      whatItDoes: 'Searches the entire codebase using vector AI + keyword search to find relevant code files.',
      whyItMatters: 'Ensures the AI has all necessary context before trying to fix any code.',
    },
    detect: {
      whatItDoes: 'Parses the code AST structure to detect hidden bugs, bare except clauses, and logic errors.',
      whyItMatters: 'Catches silent runtime failures before code is pushed to production.',
    },
    security_audit: {
      whatItDoes: 'Scans code against OWASP Top 10 security risks like SQL injection or hardcoded credentials.',
      whyItMatters: 'Prevents security vulnerabilities and data breaches in your application.',
    },
    syntax_check: {
      whatItDoes: 'Parses generated code fixes with python ast.parse and Ruff linting rules.',
      whyItMatters: 'Guarantees the AI fix will actually compile and has zero syntax errors.',
    },
    line_verifier: {
      whatItDoes: 'Cross-checks every line citation against raw source code files.',
      whyItMatters: 'Eliminates AI hallucinations so line numbers in PR comments are 100% accurate.',
    },
    test_generator: {
      whatItDoes: 'Generates unit tests and executes them live in an isolated Pytest sandbox.',
      whyItMatters: 'Proves the fix works by running real passing unit tests.',
    },
    doc_verifier: {
      whatItDoes: 'Audits function signatures and generates JSDoc / Google-style docstrings.',
      whyItMatters: 'Keeps codebase documentation clean, accurate, and up to date.',
    },
  };

  const selectedNode = pipelineState.nodes[selectedNodeId] || pipelineState.nodes['detect'];
  const nodeDetails = plainEnglishDescriptions[selectedNodeId] || plainEnglishDescriptions['detect'];

  // Helper to draw smooth SVG bezier curves with animated glowing particles
  const renderEdge = (conn: { from: string; to: string; label: string }, index: number) => {
    const fromPos = NODE_POSITIONS[conn.from];
    const toPos = NODE_POSITIONS[conn.to];
    if (!fromPos || !toPos) return null;

    const startX = fromPos.x + 230;
    const startY = fromPos.y + 50;
    const endX = toPos.x;
    const endY = toPos.y + 50;

    const controlX1 = startX + (endX - startX) * 0.45;
    const controlY1 = startY;
    const controlX2 = startX + (endX - startX) * 0.55;
    const controlY2 = endY;

    const pathData = `M ${startX} ${startY} C ${controlX1} ${controlY1}, ${controlX2} ${controlY2}, ${endX} ${endY}`;

    const fromNode = pipelineState.nodes[conn.from];
    const toNode = pipelineState.nodes[conn.to];

    const isActive = fromNode?.status === 'success' && toNode?.status === 'running';
    const isCompleted = fromNode?.status === 'success' && (toNode?.status === 'success' || toNode?.status === 'running');

    return (
      <g key={`${conn.from}-${conn.to}-${index}`}>
        {/* Glow path */}
        <path
          d={pathData}
          fill="none"
          stroke={isActive ? '#3b82f6' : isCompleted ? '#10b981' : '#2d2d38'}
          strokeWidth={isActive ? '4' : isCompleted ? '2.5' : '2'}
          strokeOpacity={isActive ? '0.9' : isCompleted ? '0.7' : '0.4'}
          className="transition-all duration-500"
        />

        {/* Dynamic animated laser flow particles */}
        {(isActive || pipelineState.isExecuting) && (
          <path
            d={pathData}
            fill="none"
            stroke={isActive ? '#60a5fa' : '#34d399'}
            strokeWidth="3.5"
            strokeDasharray="10 10"
            className="laser-line"
          />
        )}
      </g>
    );
  };

  return (
    <div className="flex-1 bg-[#0d0d12] flex flex-col h-full overflow-hidden select-none relative">
      {/* Top Friendly Explanation Banner */}
      <div className="bg-gradient-to-r from-blue-950/70 via-[#181824] to-emerald-950/70 border-b border-[#2d2d38] p-3.5 px-6 flex flex-col md:flex-row items-center justify-between gap-3 z-20 shadow-xl">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-blue-600/20 text-blue-400 rounded-xl border border-blue-500/30">
            <GitFork className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center space-x-2 text-white font-bold text-sm tracking-wide">
              <span>What is this Graph?</span>
              <span className="bg-blue-600/30 text-blue-400 text-[10px] font-mono px-2 py-0.5 rounded-full border border-blue-500/30">
                Live LangGraph Execution Workflow
              </span>
            </div>
            <p className="text-xs text-[#a0a0b8] mt-0.5">
              This visual graph shows autonomous AI agents working step-by-step to detect code bugs, verify syntax, run security audits, and generate passing unit tests.
            </p>
          </div>
        </div>

        {/* Action Button & Zoom Controls */}
        <div className="flex items-center space-x-3 flex-shrink-0">
          <div className="flex items-center space-x-1 bg-[#14141c] p-1 rounded-xl border border-[#2d2d38]">
            <button 
              onClick={() => setZoomLevel(prev => Math.min(prev + 0.1, 1.3))}
              title="Zoom In"
              className="p-1.5 text-[#858585] hover:text-white hover:bg-[#252535] rounded-lg transition-colors"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <span className="text-[11px] font-mono text-[#858585] px-1">{Math.round(zoomLevel * 100)}%</span>
            <button 
              onClick={() => setZoomLevel(prev => Math.max(prev - 0.1, 0.7))}
              title="Zoom Out"
              className="p-1.5 text-[#858585] hover:text-white hover:bg-[#252535] rounded-lg transition-colors"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button 
              onClick={() => setZoomLevel(1)}
              title="Reset View"
              className="p-1.5 text-[#858585] hover:text-white hover:bg-[#252535] rounded-lg transition-colors"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={onRunPipeline}
            disabled={pipelineState.isExecuting}
            className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-bold text-white shadow-xl transition-all transform active:scale-95 ${
              pipelineState.isExecuting
                ? 'bg-amber-600/80 cursor-not-allowed'
                : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-emerald-950/60'
            }`}
          >
            <Play className={`w-4 h-4 fill-current ${pipelineState.isExecuting ? 'animate-spin' : ''}`} />
            <span>{pipelineState.isExecuting ? 'Agent Graph Executing...' : 'Run Agent Workflow'}</span>
          </button>
        </div>
      </div>

      {/* Main Canvas Workspace */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Infinite Node Canvas */}
        <div className="flex-1 overflow-auto bg-[#0a0a0e] relative flex items-center justify-center p-8">
          {/* Glowing Background Mesh Pattern */}
          <div 
            className="absolute inset-0 pointer-events-none opacity-25"
            style={{
              backgroundImage: 'radial-gradient(#3b82f6 1.2px, transparent 1.2px)',
              backgroundSize: '28px 28px',
            }}
          />

          {/* Canvas Ambient Glows */}
          <div className="absolute top-1/3 left-1/4 w-[500px] h-[500px] bg-blue-600/10 rounded-full blur-[100px] pointer-events-none" />
          <div className="absolute bottom-1/3 right-1/4 w-[500px] h-[500px] bg-emerald-600/10 rounded-full blur-[100px] pointer-events-none" />

          {/* SVG Graph Edge Lines & Interactive Nodes */}
          <div 
            className="relative transition-transform duration-300 ease-out z-10 my-auto"
            style={{ 
              width: '1480px', 
              height: '520px', 
              transform: `scale(${zoomLevel})`,
              transformOrigin: 'center center'
            }}
          >
            {/* SVG Connecting Edges */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none z-0">
              {DAG_CONNECTIONS.map((conn, idx) => renderEdge(conn, idx))}
            </svg>

            {/* Render Node Cards */}
            {Object.entries(NODE_POSITIONS).map(([nodeKey, pos]) => {
              const node = pipelineState.nodes[nodeKey];
              if (!node) return null;

              const IconComponent = nodeIcons[nodeKey] || Cpu;
              const isSelected = selectedNodeId === nodeKey;
              const isRunning = node.status === 'running';
              const isSuccess = node.status === 'success';
              const isError = node.status === 'error';

              return (
                <div
                  key={nodeKey}
                  onClick={() => setSelectedNodeId(nodeKey)}
                  style={{
                    position: 'absolute',
                    left: `${pos.x}px`,
                    top: `${pos.y}px`,
                    width: '230px',
                  }}
                  className={`group cursor-pointer rounded-2xl border p-4 transition-all duration-300 backdrop-blur-xl z-10 shadow-2xl ${
                    isRunning
                      ? 'bg-gradient-to-b from-blue-950/90 to-[#141828] border-blue-400 shadow-[0_0_35px_rgba(59,130,246,0.7)] node-running scale-105'
                      : isSuccess
                      ? 'bg-[#14141c]/90 border-emerald-500/70 hover:border-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.3)] hover:scale-102'
                      : isError
                      ? 'bg-[#241418]/90 border-rose-500 shadow-[0_0_25px_rgba(244,63,94,0.5)]'
                      : 'bg-[#14141c]/80 border-[#2b2b38] hover:border-[#424254] hover:bg-[#1a1a24]'
                  } ${isSelected ? 'ring-2 ring-[#007acc] ring-offset-4 ring-offset-[#0a0a0e]' : ''}`}
                >
                  {/* Glowing Node Pulse Header */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2.5">
                      <div className={`p-2.5 rounded-xl transition-all ${
                        isRunning ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/60 animate-bounce' :
                        isSuccess ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' :
                        'bg-[#222230] text-[#858595]'
                      }`}>
                        <IconComponent className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="font-bold text-xs text-white tracking-wide">{node.name}</div>
                        <div className="text-[10px] text-[#858595] font-mono capitalize">{node.category} Agent</div>
                      </div>
                    </div>
                  </div>

                  <p className="text-[11px] text-[#a0a0b4] line-clamp-2 mb-3 leading-relaxed">
                    {node.description}
                  </p>

                  {/* Status Indicator Bar */}
                  <div className="flex items-center justify-between pt-2.5 border-t border-[#2d2d38] text-[10px] font-mono">
                    <span className={`px-2.5 py-0.5 rounded-full text-[9px] font-bold tracking-wider ${
                      isRunning ? 'bg-blue-950 text-blue-400 animate-pulse border border-blue-800' :
                      isSuccess ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/80 flex items-center space-x-1' :
                      'bg-[#222230] text-[#858595]'
                    }`}>
                      {isSuccess && <Check className="w-2.5 h-2.5 inline mr-1" />}
                      {node.status.toUpperCase()}
                    </span>

                    <span className="text-[#858595] flex items-center space-x-1">
                      <Clock className="w-3 h-3 text-[#60a5fa]" />
                      <span>{node.durationMs ? `${node.durationMs}ms` : '--'}</span>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Quick Legend Widget */}
          <div className="absolute bottom-5 left-5 bg-[#14141c]/90 backdrop-blur-xl px-4 py-2.5 rounded-2xl border border-[#2b2b38] text-xs text-[#858595] flex items-center space-x-5 shadow-2xl z-20">
            <span className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#2b2b38]"></span>
              <span>Pending</span>
            </span>
            <span className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-500 animate-ping"></span>
              <span className="text-blue-400 font-semibold">Running Agent</span>
            </span>
            <span className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              <span className="text-emerald-400 font-semibold">Verified Pass</span>
            </span>
          </div>
        </div>

        {/* Right Drawer: Friendly Node Explanation & Raw Payload Inspector */}
        <div className="w-[410px] bg-[#14141c] border-l border-[#2b2b38] flex flex-col h-full z-20 shadow-2xl">
          {/* Drawer Header */}
          <div className="p-4 border-b border-[#2b2b38] bg-[#181824] flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="p-1.5 bg-blue-600/20 text-blue-400 rounded-lg border border-blue-500/30">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-bold text-white">{selectedNode.name}</div>
                <div className="text-[10px] text-[#858595] font-mono">Agent Node Inspector</div>
              </div>
            </div>
            <span className="text-[10px] font-mono bg-emerald-950 text-emerald-400 px-2.5 py-1 rounded-full border border-emerald-800">
              {selectedNode.status.toUpperCase()}
            </span>
          </div>

          {/* Inspector Tab Switcher */}
          <div className="flex border-b border-[#2b2b38] bg-[#12121a] p-1 gap-1 text-xs">
            <button
              onClick={() => setInspectorTab('summary')}
              className={`flex-1 py-1.5 rounded-lg font-medium transition-colors ${
                inspectorTab === 'summary' ? 'bg-[#007acc] text-white' : 'text-[#858595] hover:text-white'
              }`}
            >
              Plain English Explanation
            </button>
            <button
              onClick={() => setInspectorTab('json')}
              className={`flex-1 py-1.5 rounded-lg font-medium transition-colors ${
                inspectorTab === 'json' ? 'bg-[#007acc] text-white' : 'text-[#858595] hover:text-white'
              }`}
            >
              State JSON
            </button>
            <button
              onClick={() => setInspectorTab('logs')}
              className={`flex-1 py-1.5 rounded-lg font-medium transition-colors ${
                inspectorTab === 'logs' ? 'bg-[#007acc] text-white' : 'text-[#858595] hover:text-white'
              }`}
            >
              Execution Logs
            </button>
          </div>

          {/* Drawer Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {inspectorTab === 'summary' && (
              <div className="space-y-4">
                <div className="bg-[#181824] p-4 rounded-2xl border border-[#2b2b38] space-y-3">
                  <div className="flex items-center space-x-2 text-blue-400 font-bold text-xs">
                    <Info className="w-4 h-4" />
                    <span>What This Agent Does:</span>
                  </div>
                  <p className="text-xs text-[#cccccc] leading-relaxed">
                    {nodeDetails.whatItDoes}
                  </p>
                </div>

                <div className="bg-[#181824] p-4 rounded-2xl border border-[#2b2b38] space-y-3">
                  <div className="flex items-center space-x-2 text-emerald-400 font-bold text-xs">
                    <ShieldCheck className="w-4 h-4" />
                    <span>Why This Matters:</span>
                  </div>
                  <p className="text-xs text-[#cccccc] leading-relaxed">
                    {nodeDetails.whyItMatters}
                  </p>
                </div>

                <div className="bg-[#0f0f16] p-3.5 rounded-2xl border border-[#2b2b38] space-y-2 font-mono text-xs">
                  <div className="flex items-center justify-between text-[#858595]">
                    <span>Stage Latency:</span>
                    <span className="text-emerald-400 font-bold">{selectedNode.durationMs || 0} ms</span>
                  </div>
                  <div className="flex items-center justify-between text-[#858595]">
                    <span>Category:</span>
                    <span className="text-blue-400 font-bold capitalize">{selectedNode.category}</span>
                  </div>
                </div>
              </div>
            )}

            {inspectorTab === 'json' && (
              <div>
                <div className="text-[11px] font-bold text-[#858595] uppercase tracking-wider mb-2">Output State Payload JSON</div>
                <div className="bg-[#0f0f16] p-4 rounded-2xl border border-[#2b2b38] font-mono text-[11px] text-[#ce9178] overflow-x-auto max-h-96 shadow-inner">
                  <pre>{JSON.stringify(selectedNode.outputPayload || {}, null, 2)}</pre>
                </div>
              </div>
            )}

            {inspectorTab === 'logs' && (
              <div>
                <div className="text-[11px] font-bold text-[#858595] uppercase tracking-wider mb-2 flex items-center space-x-1.5">
                  <Terminal className="w-3.5 h-3.5 text-[#4ec9b0]" />
                  <span>Agent Terminal Trace Logs</span>
                </div>
                <div className="bg-[#0f0f16] p-3.5 rounded-2xl border border-[#2b2b38] font-mono text-[10px] text-[#cccccc] space-y-2 max-h-96 overflow-y-auto">
                  {selectedNode.logs && selectedNode.logs.length > 0 ? (
                    selectedNode.logs.map((log, i) => (
                      <div key={i} className="flex items-start space-x-2 border-b border-[#181824] pb-1.5">
                        <span className="text-[#007acc] select-none">{i + 1}</span>
                        <span className="leading-tight text-[#dcdcaa]">{log}</span>
                      </div>
                    ))
                  ) : (
                    <div className="text-[#666666] italic">No logs generated yet.</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
