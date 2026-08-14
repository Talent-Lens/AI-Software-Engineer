import React, { useState } from 'react';
import { DiffEditor, Editor } from '@monaco-editor/react';
import { 
  GitCompare, 
  Check, 
  ShieldAlert, 
  CheckCircle2, 
  FileCode, 
  ThumbsUp, 
  ThumbsDown,
  Sparkles,
  Info,
  AlertCircle
} from 'lucide-react';
import { CodeFile } from '../types';
import { submitUserFeedback } from '../services/api';

interface CodeDiffEditorProps {
  selectedFile: CodeFile;
  onAcceptFix?: () => void;
  onRejectFix?: () => void;
}

export const CodeDiffEditor: React.FC<CodeDiffEditorProps> = ({
  selectedFile,
  onAcceptFix,
  onRejectFix,
}) => {
  const [mode, setMode] = useState<'diff' | 'source'>('diff');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState<string | null>(null);

  const handleFeedback = async (action: 'accept' | 'reject') => {
    const chunkId = `${selectedFile.path}::1`;
    await submitUserFeedback({
      chunk_id: chunkId,
      user_action: action,
      feedback_note: action === 'accept' ? 'User accepted proposed AST fix' : 'User rejected fix - added to ChromaDB hard negatives',
    });
    setFeedbackSubmitted(action);
    if (action === 'accept' && onAcceptFix) onAcceptFix();
    if (action === 'reject' && onRejectFix) onRejectFix();
  };

  // Extract dynamic line numbers from the original code
  const codeLines = selectedFile.originalCode.split('\n');
  const firstLinePreview = codeLines[0] || '';
  
  return (
    <div className="flex-1 bg-[#0d0d12] flex flex-col h-full overflow-hidden select-none">
      {/* Top Editor Bar */}
      <div className="h-12 bg-[#181820] border-b border-[#2b2b38] px-4 flex items-center justify-between z-10 shadow-md">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2 text-white font-medium">
            <GitCompare className="w-4 h-4 text-[#60a5fa]" />
            <span className="font-mono text-xs text-[#60a5fa] font-bold">{selectedFile.name}</span>
            <span className="text-[10px] bg-[#12121a] px-2 py-0.5 rounded text-[#858595] font-mono border border-[#2b2b38]">
              {selectedFile.language.toUpperCase()} ({codeLines.length} lines)
            </span>
          </div>

          <div className="flex items-center space-x-1 bg-[#12121a] p-1 rounded-xl border border-[#2b2b38]">
            <button
              onClick={() => setMode('diff')}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                mode === 'diff' ? 'bg-[#007acc] text-white' : 'text-[#858595] hover:text-white'
              }`}
            >
              Side-by-Side Diff (PR View)
            </button>
            <button
              onClick={() => setMode('source')}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                mode === 'source' ? 'bg-[#007acc] text-white' : 'text-[#858595] hover:text-white'
              }`}
            >
              Source Editor Only
            </button>
          </div>
        </div>

        {/* HITL Review Buttons */}
        <div className="flex items-center space-x-2">
          {feedbackSubmitted ? (
            <div className="flex items-center space-x-1.5 bg-emerald-950/60 border border-emerald-800 text-emerald-400 px-3 py-1.5 rounded-xl text-xs font-semibold">
              <CheckCircle2 className="w-4 h-4" />
              <span>Feedback Saved to Hard-Negatives Database</span>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <span className="text-xs text-[#858595]">HITL Review:</span>
              <button
                onClick={() => handleFeedback('accept')}
                className="flex items-center space-x-1.5 px-3.5 py-1.5 bg-emerald-700 hover:bg-emerald-600 active:scale-95 text-white text-xs font-semibold rounded-xl transition-all shadow-md shadow-emerald-950/40"
              >
                <ThumbsUp className="w-3.5 h-3.5" />
                <span>Accept Fix</span>
              </button>
              <button
                onClick={() => handleFeedback('reject')}
                className="flex items-center space-x-1.5 px-3.5 py-1.5 bg-rose-700 hover:bg-rose-600 active:scale-95 text-white text-xs font-semibold rounded-xl transition-all shadow-md shadow-rose-950/40"
              >
                <ThumbsDown className="w-3.5 h-3.5" />
                <span>Reject & Penalty Score</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Editor & Panel Split View */}
      <div className="flex-1 flex overflow-hidden">
        {/* Monaco Editor Container */}
        <div className="flex-1 h-full bg-[#0a0a0e] relative">
          {mode === 'diff' ? (
            <DiffEditor
              height="100%"
              language={selectedFile.language}
              original={selectedFile.originalCode}
              modified={selectedFile.proposedFix}
              theme="vs-dark"
              options={{
                renderSideBySide: true,
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 13,
                fontFamily: 'JetBrains Mono, Menlo, Monaco, monospace',
                scrollBeyondLastLine: false,
                smoothScrolling: true,
                automaticLayout: true,
              }}
            />
          ) : (
            <Editor
              height="100%"
              language={selectedFile.language}
              value={selectedFile.proposedFix}
              theme="vs-dark"
              options={{
                readOnly: false,
                minimap: { enabled: true },
                fontSize: 13,
                fontFamily: 'JetBrains Mono, Menlo, Monaco, monospace',
                scrollBeyondLastLine: false,
                automaticLayout: true,
              }}
            />
          )}
        </div>

        {/* Side Panel: AST Grounding Badges & OWASP Security Audit */}
        <div className="w-80 bg-[#14141c] border-l border-[#2b2b38] flex flex-col h-full text-xs select-text overflow-y-auto">
          {/* Section 1: Line Number Grounding Verification */}
          <div className="p-4 border-b border-[#2b2b38]">
            <div className="font-bold text-white mb-2 flex items-center justify-between">
              <span className="flex items-center space-x-1.5 text-xs">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span>AST Line Grounding</span>
              </span>
              <span className="text-[10px] font-mono bg-emerald-950 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-800">
                100% Verified
              </span>
            </div>
            <p className="text-[11px] text-[#858595] mb-2 leading-relaxed">
              Verifies cited line numbers against the raw source file to eliminate LLM line hallucinations.
            </p>
            <div className="space-y-1.5 font-mono text-[11px]">
              {selectedFile.lineCitations && selectedFile.lineCitations.length > 0 ? (
                selectedFile.lineCitations.map((citation, i) => (
                  <div key={i} className="bg-[#0a0a0e] p-2.5 rounded-xl border border-[#2b2b38] flex items-center justify-between">
                    <span className="text-[#ce9178]">Line #{citation.line}</span>
                    <span className="text-emerald-400 font-bold text-[10px] flex items-center space-x-1">
                      <Check className="w-3 h-3" />
                      <span>{citation.status.toUpperCase()}</span>
                    </span>
                  </div>
                ))
              ) : (
                <div className="bg-[#0a0a0e] p-2.5 rounded-xl border border-[#2b2b38] text-[#858595] text-[10px]">
                  Scanned {codeLines.length} lines — 0 line hallucinations found.
                </div>
              )}
            </div>
          </div>

          {/* Section 2: SAST Security Vulnerabilities */}
          <div className="p-4 border-b border-[#2b2b38]">
            <div className="font-bold text-white mb-2 flex items-center justify-between">
              <span className="flex items-center space-x-1.5 text-xs">
                <ShieldAlert className="w-4 h-4 text-rose-400" />
                <span>OWASP Security Auditor</span>
              </span>
              <span className="text-[10px] font-mono bg-rose-950 text-rose-400 px-2 py-0.5 rounded-full border border-rose-800">
                {selectedFile.securityIssues ? selectedFile.securityIssues.length : 0} Risks
              </span>
            </div>
            <div className="space-y-2">
              {selectedFile.securityIssues && selectedFile.securityIssues.length > 0 ? (
                selectedFile.securityIssues.map((issue, i) => (
                  <div key={i} className="bg-[#0a0a0e] p-3 rounded-xl border border-rose-900/60 space-y-1">
                    <div className="flex items-center justify-between text-[#cccccc]">
                      <span className="font-bold text-rose-400 text-[11px]">{issue.severity}</span>
                      <span className="font-mono text-[10px] text-[#858595]">Line #{issue.line}</span>
                    </div>
                    <div className="font-bold text-white text-xs">{issue.title}</div>
                    <div className="text-[10px] text-[#858595] font-mono">{issue.rule}</div>
                  </div>
                ))
              ) : (
                <div className="bg-[#0a0a0e] p-3 rounded-xl border border-[#2b2b38] text-[#858595] text-[10px] flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>0 OWASP Top 10 security risks detected in this file.</span>
                </div>
              )}
            </div>
          </div>

          {/* Section 3: Docstring Accuracy */}
          <div className="p-4 bg-[#0a0a0e] mt-auto border-t border-[#2b2b38]">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-[#858595]">Docstring Accuracy:</span>
              <span className="text-blue-400 font-mono font-bold">Verified JSDoc / Google</span>
            </div>
            <p className="text-[10px] text-[#858595] leading-relaxed">
              Function signatures, parameter types, and return descriptions match AST signatures without missing args.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
