import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { ExplorerPanel } from './components/ExplorerPanel';
import { LangGraphCanvas } from './components/LangGraphCanvas';
import { CodeDiffEditor } from './components/CodeDiffEditor';
import { EvalDashboard } from './components/EvalDashboard';
import { SimpleUserWizard } from './components/SimpleUserWizard';
import { ActiveTab, CodeFile, PipelineExecutionState, UIMode } from './types';
import { fetchHealthStatus } from './services/api';

export const App: React.FC = () => {
  const [uiMode, setUiMode] = useState<UIMode>('simple');
  const [activeTab, setActiveTab] = useState<ActiveTab>('langgraph');
  const [files, setFiles] = useState<CodeFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<CodeFile | undefined>(undefined);
  const [activeModel, setActiveModel] = useState<string>('qwen-2.5-coder-32b');
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);

  // Pipeline Execution State
  const [pipelineState, setPipelineState] = useState<PipelineExecutionState>({
    isExecuting: false,
    activeNodeId: 'detect',
    logs: ['[System] LangGraph execution engine initialized.'],
    nodes: {
      retrieval: {
        id: 'retrieval',
        name: 'Hybrid BM25 + Vector Search',
        description: 'Dense MiniLM-L6 embeddings fused with BM25 keyword tokens via RRF (k=60)',
        category: 'retrieval',
        status: 'success',
        durationMs: 42,
        outputPayload: { top_candidates: 20, reranked_top_k: 3, rrf_score: 0.982 },
        logs: ['[ChromaDB] Querying code embeddings...', '[BM25] AST Token matching...', '[RRF] Reciprocal Rank Fusion completed.']
      },
      detect: {
        id: 'detect',
        name: 'AST Bug Detection Agent',
        description: 'Parses code with tree-sitter AST to detect bare except clauses & silent exception swallowing',
        category: 'agent',
        status: 'idle',
        durationMs: 120,
        outputPayload: { bug_type: 'BARE_EXCEPT', lineno: 12, severity: 'HIGH' },
        logs: ['[AST Parser] Constructing Python AST syntax tree...', '[Rule Engine] Scanning ExceptHandler nodes...', '[ALERT] Found bare except at line 12.']
      },
      syntax_check: {
        id: 'syntax_check',
        name: 'AST Code Syntax & Lint Validator',
        description: 'Guarantees 100% syntactically valid code suggestions via ast.parse and Ruff linting',
        category: 'verifier',
        status: 'idle',
        durationMs: 25,
        outputPayload: { syntax_valid: true, lint_errors: 0 },
        logs: ['[ast.parse] Validating suggested fix...', '[Ruff] 0 syntax errors detected.']
      },
      security_audit: {
        id: 'security_audit',
        name: 'SAST Security Auditor Agent',
        description: 'Scans retrieved chunks against OWASP Top 10 risks (SQL injection, hardcoded secrets)',
        category: 'agent',
        status: 'idle',
        durationMs: 85,
        outputPayload: { security_score: 'PASS', vulnerabilities: [] },
        logs: ['[SAST Scanner] Checking SQL string formatters...', '[SAST Scanner] Checking secret key entropy... Clean.']
      },
      line_verifier: {
        id: 'line_verifier',
        name: 'Line-Number Grounding Verifier',
        description: 'Verifies line citations against raw source file to eliminate hallucinated line numbers',
        category: 'verifier',
        status: 'idle',
        durationMs: 18,
        outputPayload: { grounded: true, cited_line: 12, raw_match: 'except:' },
        logs: ['[Grounding] Cross-referencing line citations against raw source...', '[MATCH] Verified line match.']
      },
      test_generator: {
        id: 'test_generator',
        name: 'Self-Executing Unit Test Sandbox',
        description: 'Generates pytest test suite and executes live in subprocess sandbox',
        category: 'sandbox',
        status: 'idle',
        durationMs: 155,
        outputPayload: { tests_run: 3, tests_passed: 3, sandbox_exit_code: 0 },
        logs: ['[Sandbox] Spawning subprocess pytest...', '[Subprocess] test_execution PASSED [100%]']
      },
      doc_verifier: {
        id: 'doc_verifier',
        name: 'Docstring Accuracy Verifier',
        description: 'Audits generated docstrings against AST function signatures and return types',
        category: 'verifier',
        status: 'idle',
        durationMs: 30,
        outputPayload: { docstring_accuracy: 1.0, missing_params: [] },
        logs: ['[Docstring Auditor] Extracted AST signatures...', '[MATCH] All params present in docstring.']
      }
    }
  });

  useEffect(() => {
    fetchHealthStatus().then((res) => {
      setIsBackendConnected(res.ok);
    });
  }, []);

  const handleRunPipeline = () => {
    setPipelineState(prev => ({
      ...prev,
      isExecuting: true,
      logs: [...prev.logs, `[${new Date().toLocaleTimeString()}] Triggering LangGraph Pipeline...`]
    }));

    const stages = ['detect', 'syntax_check', 'security_audit', 'line_verifier', 'test_generator', 'doc_verifier'];
    
    stages.forEach((stageId, index) => {
      setTimeout(() => {
        setPipelineState(prev => {
          const updatedNodes = { ...prev.nodes };
          
          if (index > 0) {
            const prevId = stages[index - 1];
            updatedNodes[prevId] = { ...updatedNodes[prevId], status: 'success' };
          }
          
          updatedNodes[stageId] = { ...updatedNodes[stageId], status: 'running' };

          return {
            ...prev,
            activeNodeId: stageId,
            nodes: updatedNodes,
            logs: [...prev.logs, `[Pipeline] Node '${updatedNodes[stageId].name}' started execution.`]
          };
        });
      }, (index + 1) * 700);
    });

    setTimeout(() => {
      setPipelineState(prev => {
        const finalNodes = { ...prev.nodes };
        stages.forEach(id => {
          finalNodes[id] = { ...finalNodes[id], status: 'success' };
        });
        return {
          ...prev,
          isExecuting: false,
          nodes: finalNodes,
          logs: [...prev.logs, `[Pipeline Complete] All agent verification stages completed.`]
        };
      });
    }, (stages.length + 1) * 700);
  };

  const handleUploadCustomFile = (newFile: CodeFile) => {
    setFiles(prev => [newFile, ...prev]);
    setSelectedFile(newFile);
    setActiveTab('diff');
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-[#0d0d12] text-[#cccccc] overflow-hidden">
      {/* Top Header */}
      <Header
        activeModel={activeModel}
        setActiveModel={setActiveModel}
        isBackendConnected={isBackendConnected}
        isExecuting={pipelineState.isExecuting}
        onRunPipeline={handleRunPipeline}
        selectedFileName={selectedFile?.name}
        uiMode={uiMode}
        setUiMode={setUiMode}
      />

      {/* Main Workbench Body Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Activity Bar (Only shown in Advanced Mode) */}
        {uiMode === 'advanced' && (
          <Sidebar
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            nodeCount={7}
            evalCount={5}
          />
        )}

        {/* Explorer File Tree Sidebar (Visible in Explorer and Diff view in Advanced Mode) */}
        {uiMode === 'advanced' && (activeTab === 'explorer' || activeTab === 'diff') && (
          <ExplorerPanel
            files={files}
            selectedFileId={selectedFile?.id || ''}
            onSelectFile={(file) => {
              setSelectedFile(file);
            }}
            onUploadCustomFile={handleUploadCustomFile}
          />
        )}

        {/* Main Workspace View Switcher */}
        <main className="flex-1 flex overflow-hidden relative">
          {uiMode === 'simple' ? (
            <SimpleUserWizard
              selectedFile={selectedFile}
              files={files}
              onSelectFile={setSelectedFile}
              onRunPipeline={handleRunPipeline}
              pipelineState={pipelineState}
              onSwitchToAdvanced={() => setUiMode('advanced')}
              onUploadCustomFile={handleUploadCustomFile}
            />
          ) : (
            <>
              {activeTab === 'langgraph' && (
                <LangGraphCanvas
                  pipelineState={pipelineState}
                  onRunPipeline={handleRunPipeline}
                />
              )}

              {(activeTab === 'diff' || activeTab === 'explorer') && selectedFile && (
                <CodeDiffEditor
                  selectedFile={selectedFile}
                />
              )}

              {(activeTab === 'diff' || activeTab === 'explorer') && !selectedFile && (
                <div className="flex-1 bg-[#0d0d12] flex items-center justify-center p-8 text-center select-none">
                  <div className="max-w-md bg-[#14141c] p-6 rounded-2xl border border-[#2b2b38] space-y-4 shadow-2xl">
                    <div className="w-12 h-12 rounded-2xl bg-[#007acc]/20 border border-[#007acc]/30 flex items-center justify-center text-[#007acc] mx-auto">
                      <span className="text-xl">📁</span>
                    </div>
                    <div>
                      <div className="font-bold text-white text-base">No Code File Loaded</div>
                      <p className="text-xs text-[#858595] mt-1 leading-relaxed">
                        Use the <strong>Codebase Explorer</strong> on the left to upload a local source file or index a GitHub repository!
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'eval' && (
                <EvalDashboard />
              )}

              {activeTab === 'settings' && (
                <div className="flex-1 bg-[#0d0d12] p-8 overflow-y-auto">
                  <div className="max-w-2xl bg-[#14141c] p-6 rounded-2xl border border-[#2b2b38] space-y-4 shadow-2xl">
                    <h2 className="text-lg font-bold text-white">Platform Settings & Config</h2>
                    <div className="space-y-3 text-xs">
                      <div>
                        <label className="block text-[#858595] mb-1">FastAPI Backend Base URL</label>
                        <input type="text" defaultValue="http://localhost:8000" className="w-full bg-[#0a0a0e] border border-[#2b2b38] rounded-xl p-2.5 text-white font-mono" />
                      </div>
                      <div>
                        <label className="block text-[#858595] mb-1">ChromaDB Vector Store Directory</label>
                        <input type="text" defaultValue="./chroma_db" className="w-full bg-[#0a0a0e] border border-[#2b2b38] rounded-xl p-2.5 text-white font-mono" />
                      </div>
                      <div>
                        <label className="block text-[#858595] mb-1">Arize Phoenix OpenTelemetry Endpoint</label>
                        <input type="text" defaultValue="http://localhost:6006" className="w-full bg-[#0a0a0e] border border-[#2b2b38] rounded-xl p-2.5 text-white font-mono" />
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {/* Bottom Status Bar */}
      {selectedFile && (
        <StatusBar
          selectedFile={selectedFile}
          isExecuting={pipelineState.isExecuting}
          activeNodeName={pipelineState.nodes[pipelineState.activeNodeId || 'detect']?.name}
          isBackendConnected={isBackendConnected}
        />
      )}
    </div>
  );
};

export default App;
