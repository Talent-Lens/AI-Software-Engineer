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
  Layers,
  Lock
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
  retrieval: { x: 50, y: 210 },
  detect: { x: 330, y: 100 },
  security_audit: { x: 330, y: 320 },
  syntax_check: { x: 630, y: 100 },
  line_verifier: { x: 630, y: 320 },
  test_generator: { x: 930, y: 210 },
  doc_verifier: { x: 1200, y: 210 },
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
    const startY = fromPos.y + 55;
    const endX = toPos.x;
    const endY = toPos.y + 55;

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
        {/* Base Glow Path */}
        <path
          d={pathData}
          fill="none"
          stroke={isActive ? '#14b8a6' : isCompleted ? '#10b981' : '#252536'}
          strokeWidth={isActive ? '3.5' : isCompleted ? '2.5' : '1.5'}
          strokeOpacity={isActive ? '0.9' : isCompleted ? '0.7' : '0.4'}
          className="transition-all duration-500"
        />

        {/* Animated Laser Flow */}
        {(isActive || pipelineState.isExecuting) && (
          <path
            d={pathData}
            fill="none"
            stroke={isActive ? '#2dd4bf' : '#34d399'}
            strokeWidth="3"
            strokeDasharray="8 8"
            className="laser-line"
          />
        )}
      </g>
    );
  };

  return (
    <div className="flex-1 bg-[#0b0b10] flex flex-col h-full overflow-hidden select-none relative">
      {/* Top Banner */}
      <div className="bg-[#14141d] border-b border-[#252536] p-3 px-6 flex flex-col md:flex-row items-center justify-between gap-3 z-20 shadow-xl">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-teal-500/10 text-teal-400 rounded-xl border border-teal-500/30 shadow-md">
            <GitFork className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center space-x-2 text-white font-bold text-sm tracking-wide font-mono">
              <span>LangGraph Multi-Agent Architecture</span>
              <span className="bg-teal-500/20 text-teal-300 text-[10px] font-mono px-2 py-0.5 rounded-full border border-teal-500/30">
                Autonomous Directed Acyclic Graph (DAG)
              </span>
            </div>
            <p className="text-xs text-[#8e8ea6] mt-0.5">
              Click any agent node to inspect plain-English explanations, verified AST payloads, and real-time execution logs.
            </p>
          </div>
        </div>

        {/* Action Button & Zoom Controls */}
        <div className="flex items-center space-x-3 flex-shrink-0 font-mono">
          <div className="flex items-center space-x-1 bg-[#0b0b10] p-1 rounded-xl border border-[#252536]">
            <button 
              onClick={() => setZoomLevel(prev => Math.min(prev + 0.1, 1.3))}
              title="Zoom In"
              className="p-1.5 text-[#787890] hover:text-white hover:bg-[#1a1a28] rounded-lg transition-colors cursor-pointer"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <span className="text-[11px] font-mono text-teal-300 px-1">{Math.round(zoomLevel * 100)}%</span>
            <button 
              onClick={() => setZoomLevel(prev => Math.max(prev - 0.1, 0.7))}
              title="Zoom Out"
              className="p-1.5 text-[#787890] hover:text-white hover:bg-[#1a1a28] rounded-lg transition-colors cursor-pointer"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button 
              onClick={() => setZoomLevel(1)}
              title="Reset View"
              className="p-1.5 text-[#787890] hover:text-white hover:bg-[#1a1a28] rounded-lg transition-colors cursor-pointer"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={onRunPipeline}
            disabled={pipelineState.isExecuting}
            className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-bold text-white shadow-xl transition-all transform active:scale-95 cursor-pointer font-mono ${
              pipelineState.isExecuting
                ? 'bg-amber-600/80 cursor-not-allowed'
                : 'bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-400 hover:to-emerald-500 shadow-emerald-950/60'
            }`}
          >
            <Play className={`w-3.5 h-3.5 fill-current ${pipelineState.isExecuting ? 'animate-spin' : ''}`} />
            <span>{pipelineState.isExecuting ? 'Agent Graph Executing...' : 'Trigger Full Pipeline'}</span>
          </button>
        </div>
      </div>

      {/* Main Canvas Workspace */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Infinite Node Canvas */}
        <div className="flex-1 overflow-auto bg-[#08080c] relative flex items-center justify-center p-8">
          {/* Glowing Background Mesh Pattern */}
          <div 
            className="absolute inset-0 pointer-events-none opacity-20"
            style={{
              backgroundImage: 'radial-gradient(#14b8a6 1.2px, transparent 1.2px)',
              backgroundSize: '28px 28px',
            }}
          />

          {/* Ambient Cyber Glows */}
          <div className="absolute top-1/4 left-1/4 w-[400px] h-[400px] bg-teal-500/5 rounded-full blur-[120px] pointer-events-none" />
          <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] bg-emerald-500/5 rounded-full blur-[120px] pointer-events-none" />

          {/* SVG Graph Edge Lines & Interactive Nodes */}
          <div 
            className="relative transition-transform duration-300 ease-out z-10 my-auto"
            style={{ 
              width: '1460px', 
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
                      ? 'bg-gradient-to-b from-teal-950/90 to-[#121c24] border-teal-400 shadow-[0_0_35px_rgba(20,184,166,0.7)] scale-105'
                      : isSuccess
                      ? 'bg-[#14141d]/90 border-emerald-500/50 hover:border-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.2)] hover:scale-102'
                      : isError
                      ? 'bg-[#241418]/90 border-rose-500 shadow-[0_0_25px_rgba(244,63,94,0.5)]'
                      : 'bg-[#14141d]/80 border-[#252536] hover:border-teal-500/50 hover:bg-[#1a1a26]'
                  } ${isSelected ? 'ring-2 ring-teal-400 ring-offset-4 ring-offset-[#08080c]' : ''}`}
                >
                  {/* Glowing Node Pulse Header */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2.5">
                      <div className={`p-2.5 rounded-xl transition-all ${
                        isRunning ? 'bg-teal-500 text-black shadow-lg shadow-teal-500/60 animate-bounce' :
                        isSuccess ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' :
                        'bg-[#1a1a28] text-[#8e8ea6]'
                      }`}>
                        <IconComponent className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="font-bold text-xs text-white tracking-wide font-mono">{node.name}</div>
                        <div className="text-[10px] text-[#8e8ea6] font-mono capitalize">{node.category} Agent</div>
                      </div>
                    </div>
                  </div>

                  <p className="text-[11px] text-[#8e8ea6] line-clamp-2 mb-3 leading-relaxed">
                    {node.description}
                  </p>

                  {/* Status Indicator Bar */}
                  <div className="flex items-center justify-between pt-2.5 border-t border-[#252536] text-[10px] font-mono">
                    <span className={`px-2.5 py-0.5 rounded-full text-[9px] font-bold tracking-wider ${
                      isRunning ? 'bg-teal-950 text-teal-300 animate-pulse border border-teal-500' :
                      isSuccess ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-500/40 flex items-center space-x-1' :
                      'bg-[#1a1a28] text-[#8e8ea6]'
                    }`}>
                      {isSuccess && <Check className="w-2.5 h-2.5 inline mr-1" />}
                      {node.status.toUpperCase()}
                    </span>

                    <span className="text-[#8e8ea6] flex items-center space-x-1">
                      <Clock className="w-3 h-3 text-teal-400" />
                      <span>{node.durationMs ? `${node.durationMs}ms` : '--'}</span>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Quick Legend Widget */}
          <div className="absolute bottom-5 left-5 bg-[#14141d]/90 backdrop-blur-xl px-4 py-2.5 rounded-2xl border border-[#252536] text-xs text-[#8e8ea6] flex items-center space-x-5 shadow-2xl z-20 font-mono">
            <span className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#252536]"></span>
              <span>Pending</span>
            </span>
            <span className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-teal-400 animate-ping"></span>
              <span className="text-teal-300 font-semibold">Running Agent</span>
            </span>
            <span className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
              <span className="text-emerald-300 font-semibold">Verified Pass</span>
            </span>
          </div>
        </div>

        {/* Right Drawer: Friendly Node Explanation & Raw Payload Inspector */}
        <div className="w-[410px] bg-[#14141d] border-l border-[#252536] flex flex-col h-full z-20 shadow-2xl">
          {/* Drawer Header */}
          <div className="p-4 border-b border-[#252536] bg-[#101018] flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="p-1.5 bg-teal-500/10 text-teal-400 rounded-xl border border-teal-500/30">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-bold text-white font-mono">{selectedNode.name}</div>
                <div className="text-[10px] text-[#8e8ea6] font-mono">Agent Node Inspector</div>
              </div>
            </div>
            <span className="text-[10px] font-mono bg-emerald-950/60 text-emerald-400 px-2.5 py-1 rounded-full border border-emerald-500/40 font-bold">
              {selectedNode.status.toUpperCase()}
            </span>
          </div>

          {/* Inspector Tab Switcher */}
          <div className="flex border-b border-[#252536] bg-[#0b0b10] p-1 gap-1 text-xs font-mono">
            <button
              onClick={() => setInspectorTab('summary')}
              className={`flex-1 py-1.5 rounded-lg font-bold transition-all cursor-pointer ${
                inspectorTab === 'summary' ? 'bg-teal-600 text-white shadow-md' : 'text-[#8e8ea6] hover:text-white'
              }`}
            >
              Plain English
            </button>
            <button
              onClick={() => setInspectorTab('json')}
              className={`flex-1 py-1.5 rounded-lg font-bold transition-all cursor-pointer ${
                inspectorTab === 'json' ? 'bg-teal-600 text-white shadow-md' : 'text-[#8e8ea6] hover:text-white'
              }`}
            >
              State JSON
            </button>
            <button
              onClick={() => setInspectorTab('logs')}
              className={`flex-1 py-1.5 rounded-lg font-bold transition-all cursor-pointer ${
                inspectorTab === 'logs' ? 'bg-teal-600 text-white shadow-md' : 'text-[#8e8ea6] hover:text-white'
              }`}
            >
              Logs
            </button>
          </div>

          {/* Drawer Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {inspectorTab === 'summary' && (
              <div className="space-y-4">
                <div className="bg-[#0b0b10] p-4 rounded-2xl border border-[#252536] space-y-2">
                  <div className="flex items-center space-x-2 text-teal-400 font-bold text-xs font-mono">
                    <Info className="w-4 h-4" />
                    <span>Agent Purpose:</span>
                  </div>
                  <p className="text-xs text-[#c2c2d6] leading-relaxed">
                    {nodeDetails.whatItDoes}
                  </p>
                </div>

                <div className="bg-[#0b0b10] p-4 rounded-2xl border border-[#252536] space-y-2">
                  <div className="flex items-center space-x-2 text-emerald-400 font-bold text-xs font-mono">
                    <ShieldCheck className="w-4 h-4" />
                    <span>Why This Matters:</span>
                  </div>
                  <p className="text-xs text-[#c2c2d6] leading-relaxed">
                    {nodeDetails.whyItMatters}
                  </p>
                </div>

                <div className="bg-[#0b0b10] p-3.5 rounded-2xl border border-[#252536] space-y-2 font-mono text-xs">
                  <div className="flex items-center justify-between text-[#8e8ea6]">
                    <span>Stage Latency:</span>
                    <span className="text-emerald-400 font-bold">{selectedNode.durationMs || 0} ms</span>
                  </div>
                  <div className="flex items-center justify-between text-[#8e8ea6]">
                    <span>Category:</span>
                    <span className="text-teal-300 font-bold capitalize">{selectedNode.category}</span>
                  </div>
                </div>
              </div>
            )}

            {inspectorTab === 'json' && (
              <div>
                <div className="text-[11px] font-bold text-[#8e8ea6] font-mono uppercase tracking-wider mb-2">Output State Payload JSON</div>
                <div className="bg-[#0b0b10] p-4 rounded-2xl border border-[#252536] font-mono text-[11px] text-teal-300 overflow-x-auto max-h-96 shadow-inner">
                  <pre>{JSON.stringify(selectedNode.outputPayload || {}, null, 2)}</pre>
                </div>
              </div>
            )}

            {inspectorTab === 'logs' && (
              <div>
                <div className="text-[11px] font-bold text-[#8e8ea6] uppercase font-mono tracking-wider mb-2 flex items-center space-x-1.5">
                  <Terminal className="w-3.5 h-3.5 text-teal-400" />
                  <span>Agent Terminal Trace Logs</span>
                </div>
                <div className="bg-[#0b0b10] p-3.5 rounded-2xl border border-[#252536] font-mono text-[10px] text-[#c2c2d6] space-y-2 max-h-96 overflow-y-auto">
                  {selectedNode.logs && selectedNode.logs.length > 0 ? (
                    selectedNode.logs.map((log, i) => (
                      <div key={i} className="flex items-start space-x-2 border-b border-[#181824] pb-1.5">
                        <span className="text-teal-400 select-none">{i + 1}</span>
                        <span className="leading-tight text-emerald-300">{log}</span>
                      </div>
                    ))
                  ) : (
                    <div className="text-[#787890] italic">No logs generated yet.</div>
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
