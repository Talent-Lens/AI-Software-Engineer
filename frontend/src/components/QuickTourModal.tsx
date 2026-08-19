import React, { useState } from 'react';
import { 
  ShieldCheck, 
  Sparkles, 
  X, 
  ArrowRight, 
  CheckCircle2, 
  FileCode, 
  Play, 
  GitPullRequest, 
  Bug, 
  Terminal, 
  AlertCircle, 
  Layers, 
  HelpCircle,
  Code2,
  Lock,
  Cpu
} from 'lucide-react';

interface QuickTourModalProps {
  isOpen: boolean;
  onClose: () => void;
  onStartDemo: () => void;
}

export const QuickTourModal: React.FC<QuickTourModalProps> = ({
  isOpen,
  onClose,
  onStartDemo
}) => {
  const [activeTab, setActiveTab] = useState<'quickstart' | 'scope' | 'architecture'>('quickstart');

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 select-text animate-fadeIn">
      <div className="bg-[#151722] border border-[#232638] rounded-3xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        
        {/* Modal Header */}
        <div className="p-5 border-b border-[#232638] flex items-center justify-between bg-[#11131c]">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-950/50">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="font-bold text-white text-base">
                  How CodeGuardian Works
                </h3>
              </div>
              <p className="text-xs text-[#94a3b8]">
                A quick overview of what CodeGuardian does and how to use it.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="text-[#94a3b8] hover:text-white p-1.5 rounded-xl hover:bg-[#1c2030] transition-colors cursor-pointer"
            title="Close Guide"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="flex border-b border-[#232638] bg-[#11131c] px-5 gap-2 text-xs">
          <button
            onClick={() => setActiveTab('quickstart')}
            className={`pb-3 px-2 border-b-2 font-semibold transition-colors cursor-pointer flex items-center space-x-1.5 ${
              activeTab === 'quickstart'
                ? 'border-indigo-400 text-white'
                : 'border-transparent text-[#94a3b8] hover:text-white'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>3-Step Walkthrough</span>
          </button>
          
          <button
            onClick={() => setActiveTab('scope')}
            className={`pb-3 px-2 border-b-2 font-semibold transition-colors cursor-pointer flex items-center space-x-1.5 ${
              activeTab === 'scope'
                ? 'border-indigo-400 text-white'
                : 'border-transparent text-[#94a3b8] hover:text-white'
            }`}
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Scope & Capabilities</span>
          </button>

          <button
            onClick={() => setActiveTab('architecture')}
            className={`pb-3 px-2 border-b-2 font-semibold transition-colors cursor-pointer flex items-center space-x-1.5 ${
              activeTab === 'architecture'
                ? 'border-indigo-400 text-white'
                : 'border-transparent text-[#94a3b8] hover:text-white'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Verification Pipeline</span>
          </button>
        </div>

        {/* Modal Body Content */}
        <div className="p-6 overflow-y-auto space-y-5 flex-1 text-xs text-[#cbd5e1]">
          
          {/* TAB 1: 3-STEP QUICKSTART */}
          {activeTab === 'quickstart' && (
            <div className="space-y-5 animate-fadeIn">
              
              {/* Introduction Banner */}
              <div className="p-4 rounded-2xl bg-indigo-950/20 border border-indigo-500/20 space-y-2">
                <div className="flex items-center space-x-2 text-indigo-300 font-semibold text-xs">
                  <HelpCircle className="w-4 h-4" />
                  <span>Why CodeGuardian?</span>
                </div>
                <p className="text-[#94a3b8] leading-relaxed text-[11px]">
                  Traditional AI assistants often guess or make up line citations when auditing code. CodeGuardian pairs multi-agent reasoning with syntax-tree grounding and live Pytest sandbox verification to ensure every patch is 100% syntactically valid and tested.
                </p>
              </div>

              {/* 3 Steps Visual Breakdown */}
              <div className="space-y-2.5">
                <h4 className="text-white font-bold text-xs uppercase tracking-wider">
                  How To Complete Your First Review:
                </h4>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  
                  {/* Step 1 Card */}
                  <div className="p-3.5 rounded-2xl bg-[#11131c] border border-[#232638] space-y-1.5">
                    <div className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-300 font-bold flex items-center justify-center text-[10px]">
                      1
                    </div>
                    <div className="font-semibold text-white text-xs">Input Your Code</div>
                    <p className="text-[11px] text-[#94a3b8] leading-relaxed">
                      Upload your code files, provide a GitHub repo URL, or paste a snippet.
                    </p>
                  </div>

                  {/* Step 2 Card */}
                  <div className="p-3.5 rounded-2xl bg-[#11131c] border border-[#232638] space-y-1.5">
                    <div className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-300 font-bold flex items-center justify-center text-[10px]">
                      2
                    </div>
                    <div className="font-semibold text-white text-xs">Autonomous Audit</div>
                    <p className="text-[11px] text-[#94a3b8] leading-relaxed">
                      Agents scan for OWASP flaws, ground line citations, and execute tests.
                    </p>
                  </div>

                  {/* Step 3 Card */}
                  <div className="p-3.5 rounded-2xl bg-[#11131c] border border-[#232638] space-y-1.5">
                    <div className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-300 font-bold flex items-center justify-center text-[10px]">
                      3
                    </div>
                    <div className="font-semibold text-white text-xs">Review & Export</div>
                    <p className="text-[11px] text-[#94a3b8] leading-relaxed">
                      Inspect the side-by-side diff, download the fix, or open a GitHub PR.
                    </p>
                  </div>

                </div>
              </div>

              {/* 1-Click Interactive Demo CTA */}
              <div className="p-4 rounded-2xl bg-[#11131c] border border-indigo-500/30 flex flex-col sm:flex-row items-center justify-between gap-3">
                <div>
                  <div className="font-semibold text-white text-xs flex items-center space-x-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Try with sample project</span>
                  </div>
                  <p className="text-[11px] text-[#94a3b8] mt-0.5">
                    Loads the SMS-Spam-Classifier with a real OWASP pickle vulnerability.
                  </p>
                </div>
                <button
                  onClick={() => {
                    onClose();
                    onStartDemo();
                  }}
                  className="w-full sm:w-auto px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-semibold transition-all cursor-pointer flex items-center justify-center space-x-1.5 shadow-sm text-xs flex-shrink-0"
                >
                  <span>Launch Demo</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>

            </div>
          )}

          {/* TAB 2: SUPPORTED SCOPE */}
          {activeTab === 'scope' && (
            <div className="space-y-4 animate-fadeIn">
              
              {/* Top Overview Callout */}
              <div className="p-3.5 rounded-2xl bg-indigo-950/20 border border-indigo-500/20 flex items-start space-x-2.5">
                <Sparkles className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
                <div className="text-[11px] text-[#94a3b8] leading-relaxed">
                  <strong className="text-white">Production Scope Reference: </strong>
                  CodeGuardian operates as an automated security auditor, AST patch generator, and context-aware Q&A assistant. Every patch is grounded against syntax trees and verified via test execution.
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                
                {/* Card 1: Supported File Types & Languages */}
                <div className="p-4 rounded-2xl bg-[#11131c] border border-[#232638] space-y-2.5">
                  <div className="flex items-center space-x-2 text-indigo-300 font-semibold text-xs">
                    <FileCode className="w-4 h-4 text-indigo-400" />
                    <span>Supported File Types & Formats</span>
                  </div>
                  <ul className="space-y-1.5 text-[11px] text-[#94a3b8] list-disc list-inside leading-relaxed">
                    <li><strong className="text-white">Jupyter Notebooks:</strong> <code className="text-indigo-300">.ipynb</code> (code cell extraction & analysis).</li>
                    <li><strong className="text-white">Python:</strong> <code className="text-indigo-300">.py</code> (Tree-Sitter AST & Pytest sandbox).</li>
                    <li><strong className="text-white">TypeScript / JS:</strong> <code className="text-indigo-300">.ts</code>, <code className="text-indigo-300">.tsx</code>, <code className="text-indigo-300">.js</code>, <code className="text-indigo-300">.jsx</code>.</li>
                    <li><strong className="text-white">Systems & Backend:</strong> <code className="text-indigo-300">.go</code>, <code className="text-indigo-300">.java</code>, <code className="text-indigo-300">.rs</code>, <code className="text-indigo-300">.cpp</code>.</li>
                    <li><strong className="text-white">Data & Config:</strong> <code className="text-indigo-300">.sql</code>, <code className="text-indigo-300">.json</code>, <code className="text-indigo-300">.yaml</code>, <code className="text-indigo-300">.yml</code>.</li>
                  </ul>
                </div>

                {/* Card 2: 7-Stage Verification Pipeline */}
                <div className="p-4 rounded-2xl bg-[#11131c] border border-emerald-500/20 space-y-2.5">
                  <div className="flex items-center space-x-2 text-emerald-400 font-semibold text-xs">
                    <Layers className="w-4 h-4" />
                    <span>7-Stage Verification Pipeline</span>
                  </div>
                  <ul className="space-y-1 text-[11px] text-[#94a3b8] list-decimal list-inside leading-relaxed">
                    <li><strong className="text-white">Retrieval:</strong> ChromaDB + BM25 RRF hybrid search.</li>
                    <li><strong className="text-white">AST Bug Detection:</strong> Tree-Sitter syntax patterns.</li>
                    <li><strong className="text-white">Syntax Check:</strong> Ruff & AST compilation validation.</li>
                    <li><strong className="text-white">Security Audit:</strong> OWASP Top 10 & CWE scanner.</li>
                    <li><strong className="text-white">Line Verifier:</strong> 100% verified citation grounding.</li>
                    <li><strong className="text-white">Test Sandbox:</strong> Subprocess isolated test runner.</li>
                    <li><strong className="text-white">Doc Verifier:</strong> Signature & docstring auditor.</li>
                  </ul>
                </div>

                {/* Card 3: Interactive Q&A Chat Capability */}
                <div className="p-4 rounded-2xl bg-[#11131c] border border-indigo-500/30 space-y-2.5">
                  <div className="flex items-center space-x-2 text-indigo-300 font-semibold text-xs">
                    <Sparkles className="w-4 h-4 text-indigo-400" />
                    <span>Restored Q&A Chat (Qwen-2.5 Coder 32B)</span>
                  </div>
                  <ul className="space-y-1.5 text-[11px] text-[#94a3b8] list-disc list-inside leading-relaxed">
                    <li><strong className="text-white">What it does:</strong> Context-aware code explanations, risk rationale breakdowns, fix explanations, and follow-up queries.</li>
                    <li><strong className="text-white">Clickable Line Jump:</strong> Chat citations link directly to line numbers in the Monaco editor.</li>
                    <li><strong className="text-white">Per-File History:</strong> Preserves conversation threads per active source file.</li>
                  </ul>
                </div>

                {/* Card 4: Limitations & Operational Boundaries */}
                <div className="p-4 rounded-2xl bg-[#11131c] border border-amber-500/20 space-y-2.5">
                  <div className="flex items-center space-x-2 text-amber-400 font-semibold text-xs">
                    <AlertCircle className="w-4 h-4" />
                    <span>Limitations & Boundaries</span>
                  </div>
                  <ul className="space-y-1.5 text-[11px] text-[#94a3b8] list-disc list-inside leading-relaxed">
                    <li><strong className="text-white">Vulnerability Scope:</strong> OWASP A01, A03, A08 (pickle), hardcoded secrets, and swallowed exceptions.</li>
                    <li><strong className="text-white">Repo Limits:</strong> Recommended &lt;50MB / 10-15 key files per interactive review session.</li>
                    <li><strong className="text-white">Private Repos:</strong> Supported with Personal Access Tokens (stored in-memory only).</li>
                    <li><strong className="text-white">Human Review:</strong> All patches are presented as diffs; partial complex patches require manual sign-off.</li>
                  </ul>
                </div>

              </div>
            </div>
          )}


          {/* TAB 3: PIPELINE (7-AGENT NODES) */}
          {activeTab === 'architecture' && (
            <div className="space-y-3 animate-fadeIn">
              <div className="flex items-center justify-between">
                <p className="text-[11px] text-[#94a3b8] leading-relaxed">
                  CodeGuardian coordinates a 7-agent verification Directed Acyclic Graph (DAG) before proposing any patch:
                </p>
                <span className="text-[10px] bg-indigo-500/10 text-indigo-300 font-semibold px-2 py-0.5 rounded-full border border-indigo-500/20 flex-shrink-0">
                  7 Active Nodes
                </span>
              </div>

              <div className="space-y-2 max-h-[48vh] overflow-y-auto pr-1">
                {[
                  { title: 'Retrieval Agent', desc: 'Retrieves relevant repository context and symbols for analysis.' },
                  { title: 'AST Bug Detector', desc: 'Builds Tree-Sitter syntax trees and scans code for bugs.' },
                  { title: 'Syntax Verifier', desc: 'Validates proposed fixes for syntactic correctness.' },
                  { title: 'SAST Security Auditor', desc: 'Scans for OWASP Top 10 risks and security vulnerabilities.' },
                  { title: 'Line Grounding Verifier', desc: 'Confirms line numbers and grounding accuracy of suggested fixes.' },
                  { title: 'Pytest Test Sandbox', desc: 'Executes unit tests in an isolated subprocess to confirm fix correctness.' },
                  { title: 'Docstring Auto-Verifier', desc: 'Validates and generates accurate docstrings for changes.' },
                ].map((step, i) => (
                  <div key={i} className="p-3 rounded-2xl bg-[#11131c] border border-[#232638] flex items-start space-x-3 hover:border-[#2f354d] transition-colors">
                    <div className="w-6 h-6 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 flex items-center justify-center text-[10px] font-bold mt-0.5 flex-shrink-0">
                      {i + 1}
                    </div>
                    <div>
                      <div className="font-semibold text-white text-xs">{step.title}</div>
                      <div className="text-[11px] text-[#94a3b8] mt-0.5 leading-relaxed">{step.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-[#232638] bg-[#11131c] flex items-center justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-semibold transition-colors cursor-pointer text-xs"
          >
            Got it, Let's Review
          </button>
        </div>

      </div>
    </div>
  );
};
