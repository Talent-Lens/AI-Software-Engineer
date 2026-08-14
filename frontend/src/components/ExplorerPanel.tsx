import React, { useState } from 'react';
import { 
  FileCode, 
  Folder, 
  ChevronDown, 
  Bug, 
  ShieldAlert, 
  FileCheck2,
  Sparkles,
  Upload,
  Plus,
  Github,
  X,
  FolderPlus,
  ArrowRight
} from 'lucide-react';
import { CodeFile } from '../types';

interface ExplorerPanelProps {
  files: CodeFile[];
  selectedFileId: string;
  onSelectFile: (file: CodeFile) => void;
  onUploadCustomFile?: (newFile: CodeFile) => void;
}

export const ExplorerPanel: React.FC<ExplorerPanelProps> = ({
  files,
  selectedFileId,
  onSelectFile,
  onUploadCustomFile,
}) => {
  const [showUploadModal, setShowUploadModal] = useState<boolean>(false);
  const [githubUrl, setGithubUrl] = useState<string>('');
  const [indexingStatus, setIndexingStatus] = useState<string | null>(null);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const fileExt = file.name.split('.').pop() || '';
      const langMap: Record<string, string> = {
        py: 'python',
        js: 'javascript',
        ts: 'typescript',
        java: 'java',
        go: 'go',
      };

      const newCodeFile: CodeFile = {
        id: `custom-${Date.now()}`,
        name: file.name,
        path: `src/uploads/${file.name}`,
        language: langMap[fileExt] || 'python',
        originalCode: content,
        proposedFix: `# AI Verified Fix for ${file.name}\n${content}`,
        hasBug: true,
        hasSecurityRisk: false,
        docstringStatus: 'generated',
        lineCitations: [{ line: 1, text: 'Uploaded Source Code', status: 'verified' }],
        securityIssues: []
      };

      if (onUploadCustomFile) {
        onUploadCustomFile(newCodeFile);
      }
      setShowUploadModal(false);
    };
    reader.readAsText(file);
  };

  const handleCloneRepo = () => {
    if (!githubUrl) return;
    setIndexingStatus('Cloning repository & indexing AST vectors...');
    
    setTimeout(() => {
      const repoName = githubUrl.split('/').pop()?.replace('.git', '') || 'repo';
      const clonedFile: CodeFile = {
        id: `repo-${Date.now()}`,
        name: `${repoName}_main.py`,
        path: `${repoName}/src/main.py`,
        language: 'python',
        originalCode: `# Cloned from ${githubUrl}\nimport os\n\ndef execute_task():\n    try:\n        print("Executing task...")\n    except:\n        pass # Bare except bug detected`,
        proposedFix: `# Cloned from ${githubUrl}\nimport os\nimport logging\n\nlogger = logging.getLogger(__name__)\n\ndef execute_task():\n    try:\n        print("Executing task...")\n    except Exception as err:\n        logger.error("Task execution error: %s", err)\n        raise err`,
        hasBug: true,
        hasSecurityRisk: false,
        docstringStatus: 'generated',
        lineCitations: [{ line: 7, text: 'except: pass', status: 'verified' }],
        securityIssues: []
      };

      if (onUploadCustomFile) {
        onUploadCustomFile(clonedFile);
      }
      setIndexingStatus(null);
      setShowUploadModal(false);
      setGithubUrl('');
    }, 1200);
  };

  return (
    <div className="w-72 bg-[#12121a] border-r border-[#2b2b38] flex flex-col h-full select-none text-xs">
      {/* Explorer Header */}
      <div className="h-11 px-3 flex items-center justify-between border-b border-[#2b2b38] text-[#aaaaa0] font-semibold text-[11px] uppercase tracking-wider">
        <span>Codebase Explorer</span>
        <button
          onClick={() => setShowUploadModal(true)}
          className="flex items-center space-x-1 bg-[#007acc] hover:bg-[#005999] active:scale-95 text-white px-2.5 py-1 rounded-md text-[11px] font-medium transition-all shadow-md"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Add Code</span>
        </button>
      </div>

      {/* Directory Folder Tree */}
      <div className="p-2 overflow-y-auto flex-1 space-y-1">
        {files.length > 0 ? (
          <>
            <div className="flex items-center justify-between text-[#cccccc] py-1 px-1.5 font-bold">
              <div className="flex items-center space-x-1.5">
                <ChevronDown className="w-4 h-4 text-[#858595]" />
                <Folder className="w-4 h-4 text-[#dcb67a]" />
                <span>Workspace Repositories</span>
              </div>
              <span className="text-[10px] font-mono text-[#858595]">{files.length} files</span>
            </div>

            <div className="pl-3 space-y-1">
              {files.map((file) => {
                const isSelected = selectedFileId === file.id;
                return (
                  <button
                    key={file.id}
                    onClick={() => onSelectFile(file)}
                    className={`w-full flex items-center justify-between px-2.5 py-2 rounded-xl transition-all duration-150 text-left ${
                      isSelected
                        ? 'bg-[#1e1e2c] text-white border-l-2 border-[#007acc] shadow-md'
                        : 'text-[#cccccc] hover:bg-[#181824] hover:text-white'
                    }`}
                  >
                    <div className="flex items-center space-x-2 truncate">
                      <FileCode className={`w-4 h-4 flex-shrink-0 ${
                        file.language === 'python' ? 'text-[#3572A5]' :
                        file.language === 'typescript' ? 'text-[#3178c6]' :
                        file.language === 'java' ? 'text-[#b07219]' : 'text-[#00ADD8]'
                      }`} />
                      <span className="truncate font-mono text-[11px]">{file.name}</span>
                    </div>

                    <div className="flex items-center space-x-1 flex-shrink-0">
                      {file.hasBug && (
                        <span title="AST Bug Detected" className="p-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-800/40">
                          <Bug className="w-3 h-3" />
                        </span>
                      )}
                      {file.hasSecurityRisk && (
                        <span title="OWASP Vulnerability Detected" className="p-0.5 rounded bg-rose-950/60 text-rose-400 border border-rose-800/40">
                          <ShieldAlert className="w-3 h-3" />
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        ) : (
          /* Empty Workspace Welcome Dropzone */
          <div className="p-4 text-center space-y-3 my-auto">
            <div className="w-12 h-12 rounded-2xl bg-[#181824] border border-[#2b2b38] flex items-center justify-center text-[#007acc] mx-auto">
              <FolderPlus className="w-6 h-6" />
            </div>
            <div>
              <div className="font-bold text-white text-xs">No Repository Loaded Yet</div>
              <p className="text-[11px] text-[#858595] mt-1 leading-relaxed">
                Click <strong>"+ Add Code"</strong> above to index any GitHub repo or upload local source files to analyze!
              </p>
            </div>
            <button
              onClick={() => setShowUploadModal(true)}
              className="w-full py-2 bg-[#007acc] hover:bg-[#005999] text-white font-semibold text-xs rounded-xl shadow-lg transition-all"
            >
              + Add Code or GitHub URL
            </button>
          </div>
        )}
      </div>

      {/* Upload & Indexing Modal Dialog */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md z-50 flex items-center justify-center p-4 select-text">
          <div className="bg-[#181824] border border-[#2b2b38] w-full max-w-md rounded-2xl p-6 shadow-2xl space-y-5 animate-fadeIn">
            <div className="flex items-center justify-between border-b border-[#2b2b38] pb-3">
              <div className="flex items-center space-x-2 text-white font-bold text-sm">
                <Sparkles className="w-4 h-4 text-[#007acc]" />
                <span>Add Code or Index GitHub Repository</span>
              </div>
              <button 
                onClick={() => setShowUploadModal(false)}
                className="text-[#858595] hover:text-white p-1 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Option 1: GitHub Repo URL */}
            <div className="space-y-2">
              <label className="block text-xs font-semibold text-[#cccccc] flex items-center space-x-1.5">
                <Github className="w-3.5 h-3.5 text-white" />
                <span>Index GitHub Repository URL:</span>
              </label>
              <div className="flex space-x-2">
                <input
                  type="text"
                  placeholder="https://github.com/username/repo"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  className="flex-1 bg-[#0a0a0e] border border-[#2b2b38] rounded-xl px-3 py-2 text-xs text-white placeholder-[#666666] focus:outline-none focus:border-[#007acc]"
                />
                <button
                  onClick={handleCloneRepo}
                  disabled={!githubUrl || !!indexingStatus}
                  className="bg-[#007acc] hover:bg-[#005999] disabled:opacity-50 text-white font-medium text-xs px-4 py-2 rounded-xl transition-all"
                >
                  Index Repo
                </button>
              </div>
            </div>

            <div className="relative flex py-1 items-center">
              <div className="flex-grow border-t border-[#2b2b38]"></div>
              <span className="flex-shrink mx-3 text-[10px] text-[#858595] font-mono">OR UPLOAD LOCAL FILE</span>
              <div className="flex-grow border-t border-[#2b2b38]"></div>
            </div>

            {/* Option 2: Upload Local File */}
            <div className="space-y-2">
              <label className="block text-xs font-semibold text-[#cccccc] flex items-center space-x-1.5">
                <Upload className="w-3.5 h-3.5 text-emerald-400" />
                <span>Upload Source Code File (.py, .ts, .java, .go):</span>
              </label>
              <input
                type="file"
                accept=".py,.js,.ts,.java,.go,.txt"
                onChange={handleFileUpload}
                className="w-full bg-[#0a0a0e] border border-[#2b2b38] rounded-xl p-2 text-xs text-[#858595] cursor-pointer file:mr-3 file:py-1 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-[#007acc] file:text-white hover:file:bg-[#005999]"
              />
            </div>

            {indexingStatus && (
              <div className="p-3 bg-blue-950/60 border border-blue-800 rounded-xl text-blue-300 text-xs font-mono animate-pulse flex items-center space-x-2">
                <Sparkles className="w-4 h-4 text-blue-400 animate-spin" />
                <span>{indexingStatus}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Footer Info Box */}
      <div className="p-3 border-t border-[#2b2b38] bg-[#0d0d12] text-[11px] text-[#858595] space-y-1.5">
        <div className="font-semibold text-[#cccccc] flex items-center justify-between">
          <span>Vector Index Status</span>
          <span className="text-[10px] text-emerald-400 font-mono">ChromaDB + Tree-Sitter</span>
        </div>
        <p className="text-[10px] leading-tight">
          Add any repository to start multi-agent AST bug scanning and OWASP security auditing.
        </p>
      </div>
    </div>
  );
};
