import React, { useState, useRef } from 'react';
import { 
  Github, 
  ShieldCheck, 
  Cpu, 
  FileCode, 
  Upload, 
  Sparkles, 
  Layers, 
  ShieldAlert, 
  CheckCircle2, 
  FolderOpen,
  Code2,
  Terminal,
  Play,
  ArrowRight,
  RefreshCw,
  AlertCircle
} from 'lucide-react';
import { CodeFile } from '../types';
import { analyzeCodeFile } from '../utils/codeAnalyzer';

interface DeveloperLandingProps {
  onUploadCustomFile: (file: CodeFile) => void;
  onUploadMultipleFiles?: (files: CodeFile[]) => void;
}

export const DeveloperLanding: React.FC<DeveloperLandingProps> = ({
  onUploadCustomFile,
  onUploadMultipleFiles,
}) => {
  const [activeTab, setActiveTab] = useState<'upload' | 'github' | 'paste'>('upload');
  const [dragOver, setDragOver] = useState(false);
  const [githubUrl, setGithubUrl] = useState('');
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  const [pastedCode, setPastedCode] = useState('');
  const [pastedFileName, setPastedFileName] = useState('main.py');

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const parsedFile = analyzeCodeFile(file.name, content);
      onUploadCustomFile(parsedFile);
    };
    reader.readAsText(file);
  };

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const parsedFile = analyzeCodeFile(file.name, content);
      onUploadCustomFile(parsedFile);
    };
    reader.readAsText(file);
  };

  const handleIndexGithub = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!githubUrl.trim()) return;

    setIsIndexing(true);
    setIndexError(null);

    try {
      // Parse owner and repo from URL
      const cleanUrl = githubUrl.trim().replace(/\.git$/, '').replace(/\/$/, '');
      const parts = cleanUrl.split('github.com/');
      let ownerRepo = parts[1] ? parts[1] : cleanUrl;
      const [owner, repo] = ownerRepo.split('/');

      if (!owner || !repo) {
        throw new Error('Please enter a valid GitHub URL (e.g. https://github.com/owner/repository)');
      }

      // Fetch repository contents via GitHub API
      const apiUrl = `https://api.github.com/repos/${owner}/${repo}/contents`;
      const res = await fetch(apiUrl);
      
      if (!res.ok) {
        throw new Error(`GitHub repository '${owner}/${repo}' returned ${res.statusText}. Check repository visibility.`);
      }

      const items = await res.json();
      const codeFilesToFetch = items.filter((item: any) => 
        item.type === 'file' && (
          item.name.endsWith('.py') || 
          item.name.endsWith('.ts') || 
          item.name.endsWith('.js') || 
          item.name.endsWith('.tsx') || 
          item.name.endsWith('.jsx') || 
          item.name.endsWith('.java') || 
          item.name.endsWith('.go') || 
          item.name.endsWith('.txt') ||
          item.name.endsWith('.md')
        )
      );

      if (codeFilesToFetch.length === 0) {
        throw new Error('No source code files found in the root of this repository.');
      }

      // Fetch actual raw contents for all files in the repository
      const parsedFiles: CodeFile[] = [];
      for (const item of codeFilesToFetch) {
        try {
          const rawRes = await fetch(item.download_url);
          if (rawRes.ok) {
            const rawText = await rawRes.text();
            parsedFiles.push(analyzeCodeFile(item.name, rawText, `${repo}/${item.path}`));
          }
        } catch (fetchErr) {
          console.warn(`Failed fetching file ${item.name}:`, fetchErr);
        }
      }

      if (parsedFiles.length > 0) {
        if (onUploadMultipleFiles) {
          onUploadMultipleFiles(parsedFiles);
        } else {
          onUploadCustomFile(parsedFiles[0]);
        }
        setGithubUrl('');
      } else {
        throw new Error('Failed to download source files from GitHub repository.');
      }
    } catch (err: any) {
      console.error('GitHub indexing failed:', err);
      setIndexError(err.message || 'Failed to index GitHub repository');
    } finally {
      setIsIndexing(false);
    }
  };

  const handleAuditPastedCode = () => {
    if (!pastedCode.trim()) return;
    const parsedFile = analyzeCodeFile(pastedFileName || 'snippet.py', pastedCode);
    onUploadCustomFile(parsedFile);
  };

  return (
    <div className="flex-1 bg-[#090910] text-[#cccccc] flex flex-col items-center justify-center p-6 select-none overflow-y-auto">
      <div className="max-w-3xl w-full space-y-6 animate-fadeIn">
        
        {/* Hidden Native File Input */}
        <input 
          type="file" 
          ref={fileInputRef} 
          onChange={handleFileChange} 
          accept=".py,.js,.ts,.tsx,.jsx,.java,.go,.rs,.cpp,.c,.json,.sql"
          className="hidden" 
        />

        {/* Hero Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-teal-500/10 border border-teal-500/30 text-teal-300 text-xs font-mono">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Autonomous Multi-Agent AST & SAST Code Guardian</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Developer Workspace
          </h1>
          <p className="text-xs sm:text-sm text-[#8e8ea6] max-w-lg mx-auto leading-relaxed">
            Select a project source file, connect a GitHub repository, or paste code to execute automated AST syntax audits and OWASP vulnerability repair.
          </p>
        </div>

        {/* Unified Hub Container */}
        <div className="bg-[#12121c] border border-[#222234] rounded-2xl shadow-xl overflow-hidden">
          
          {/* Top Segmented Navigation Tabs */}
          <div className="flex items-center border-b border-[#222234] bg-[#0e0e16] px-4 pt-3 gap-2">
            <button
              onClick={() => { setActiveTab('upload'); setIndexError(null); }}
              className={`flex items-center space-x-2 px-4 py-2 rounded-t-xl text-xs font-mono font-semibold transition-all border-t border-x cursor-pointer ${
                activeTab === 'upload'
                  ? 'bg-[#12121c] text-teal-300 border-[#222234] border-b-transparent shadow-sm'
                  : 'text-[#787890] hover:text-white border-transparent'
              }`}
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Local File Upload</span>
            </button>

            <button
              onClick={() => { setActiveTab('github'); setIndexError(null); }}
              className={`flex items-center space-x-2 px-4 py-2 rounded-t-xl text-xs font-mono font-semibold transition-all border-t border-x cursor-pointer ${
                activeTab === 'github'
                  ? 'bg-[#12121c] text-cyan-300 border-[#222234] border-b-transparent shadow-sm'
                  : 'text-[#787890] hover:text-white border-transparent'
              }`}
            >
              <Github className="w-3.5 h-3.5" />
              <span>GitHub Repository</span>
            </button>

            <button
              onClick={() => { setActiveTab('paste'); setIndexError(null); }}
              className={`flex items-center space-x-2 px-4 py-2 rounded-t-xl text-xs font-mono font-semibold transition-all border-t border-x cursor-pointer ${
                activeTab === 'paste'
                  ? 'bg-[#12121c] text-emerald-300 border-[#222234] border-b-transparent shadow-sm'
                  : 'text-[#787890] hover:text-white border-transparent'
              }`}
            >
              <Code2 className="w-3.5 h-3.5" />
              <span>Live Code Snippet</span>
            </button>
          </div>

          {/* Tab 1: Local File Dropzone & Browse */}
          {activeTab === 'upload' && (
            <div className="p-6 space-y-4 animate-fadeIn">
              <div 
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleFileDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl p-8 text-center transition-all cursor-pointer flex flex-col items-center justify-center space-y-3 ${
                  dragOver 
                    ? 'border-teal-400 bg-teal-950/20 text-teal-300' 
                    : 'border-[#28283c] bg-[#0e0e16] text-[#8e8ea6] hover:border-teal-500/50 hover:bg-[#141422]'
                }`}
              >
                <div className="w-12 h-12 rounded-2xl bg-teal-500/10 border border-teal-500/30 flex items-center justify-center text-teal-400">
                  <FolderOpen className="w-6 h-6" />
                </div>
                <div>
                  <div className="font-bold text-white text-sm font-mono">
                    Drop your source code file here, or <span className="text-teal-400 underline">Browse Files</span>
                  </div>
                  <p className="text-xs text-[#787890] mt-1 font-mono">
                    Supports Python (.py), TypeScript (.ts, .tsx), JavaScript (.js), Java (.java), Go (.go), SQL (.sql)
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-between text-xs text-[#787890] font-mono pt-1">
                <span>AST Parser Engine: Tree-Sitter Ready</span>
                <span>Automatic OWASP Top 10 SAST Scan</span>
              </div>
            </div>
          )}

          {/* Tab 2: GitHub Repository Indexer */}
          {activeTab === 'github' && (
            <div className="p-6 space-y-5 animate-fadeIn">
              <div className="space-y-2">
                <label className="block text-xs font-bold text-cyan-300 font-mono flex items-center space-x-1.5">
                  <Github className="w-4 h-4 text-white" />
                  <span>Enter Public or Private GitHub Repository URL:</span>
                </label>
                <form onSubmit={handleIndexGithub} className="flex space-x-2">
                  <input
                    type="text"
                    placeholder="https://github.com/Pranjal-png/SMS-Spam-Classifier"
                    value={githubUrl}
                    onChange={(e) => setGithubUrl(e.target.value)}
                    className="flex-1 bg-[#0e0e16] border border-[#252536] rounded-xl px-3.5 py-2.5 text-xs text-white placeholder-[#55556d] focus:outline-none focus:border-cyan-500 font-mono"
                  />
                  <button
                    type="submit"
                    disabled={!githubUrl.trim() || isIndexing}
                    className="bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 disabled:opacity-40 text-white font-bold text-xs px-5 py-2.5 rounded-xl transition-all cursor-pointer font-mono flex items-center space-x-1.5 shadow-sm"
                  >
                    {isIndexing ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        <span>Downloading & Indexing AST...</span>
                      </>
                    ) : (
                      <>
                        <span>Index Repository</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </>
                    )}
                  </button>
                </form>
              </div>

              {indexError && (
                <div className="p-3 bg-rose-950/50 border border-rose-500/40 rounded-xl text-rose-300 text-xs font-mono flex items-center space-x-2">
                  <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
                  <span>{indexError}</span>
                </div>
              )}

              <div className="bg-[#0e0e16] p-3.5 rounded-xl border border-[#222234] text-xs font-mono text-[#8e8ea6] space-y-1">
                <div className="font-bold text-white text-[11px] flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Real Codebase Indexing</span>
                </div>
                <p className="text-[11px] text-[#787890] leading-relaxed">
                  Fetches actual source code files from GitHub, constructs Tree-Sitter AST symbol graphs, and detects real security & logic bugs.
                </p>
              </div>
            </div>
          )}

          {/* Tab 3: Paste & Live Audit */}
          {activeTab === 'paste' && (
            <div className="p-6 space-y-4 animate-fadeIn">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <FileCode className="w-4 h-4 text-emerald-400" />
                  <input 
                    type="text"
                    value={pastedFileName}
                    onChange={(e) => setPastedFileName(e.target.value)}
                    className="bg-[#0e0e16] border border-[#252536] rounded-lg px-2.5 py-1 text-xs text-emerald-300 font-mono focus:outline-none focus:border-emerald-500"
                    placeholder="filename.py"
                  />
                </div>
                <button
                  onClick={handleAuditPastedCode}
                  className="flex items-center space-x-1.5 px-4 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-bold font-mono rounded-xl shadow-sm transition-all cursor-pointer"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Audit & Generate Fix</span>
                </button>
              </div>

              <textarea
                value={pastedCode}
                onChange={(e) => setPastedCode(e.target.value)}
                rows={7}
                className="w-full bg-[#08080c] border border-[#252536] rounded-xl p-3 text-xs text-emerald-200 font-mono focus:outline-none focus:border-emerald-500 resize-none leading-relaxed select-text"
                placeholder="# Paste your Python, JavaScript, TypeScript, Go, or Java code here to audit..."
              />
            </div>
          )}

        </div>

        {/* Feature Highlights Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px] font-mono text-[#787890]">
          <div className="flex items-center space-x-2 bg-[#101018] p-2.5 rounded-xl border border-[#1e1e2c]">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
            <span>Tree-Sitter AST</span>
          </div>
          <div className="flex items-center space-x-2 bg-[#101018] p-2.5 rounded-xl border border-[#1e1e2c]">
            <ShieldAlert className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />
            <span>OWASP Top 10 SAST</span>
          </div>
          <div className="flex items-center space-x-2 bg-[#101018] p-2.5 rounded-xl border border-[#1e1e2c]">
            <Cpu className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
            <span>LangGraph Multi-Agent</span>
          </div>
          <div className="flex items-center space-x-2 bg-[#101018] p-2.5 rounded-xl border border-[#1e1e2c]">
            <Layers className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
            <span>Grounded Line Diffs</span>
          </div>
        </div>

      </div>
    </div>
  );
};
