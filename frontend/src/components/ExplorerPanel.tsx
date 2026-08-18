import React, { useState } from 'react';
import { analyzeCodeFile } from '../utils/codeAnalyzer';
import { 
  FileCode, 
  Folder, 
  ChevronDown, 
  Bug, 
  ShieldAlert, 
  Upload, 
  Plus, 
  Github, 
  X, 
  FolderPlus, 
  Search,
  CheckCircle2,
  Layers,
  Code2,
  Sparkles,
  AlertCircle,
  Copy,
  Check,
  PanelLeftClose
} from 'lucide-react';
import { CodeFile } from '../types';

interface ExplorerPanelProps {
  files: CodeFile[];
  selectedFileId: string;
  onSelectFile: (file: CodeFile) => void;
  onUploadCustomFile?: (newFile: CodeFile) => void;
  onToggleCollapse?: () => void;
}

export const ExplorerPanel: React.FC<ExplorerPanelProps> = ({
  files,
  selectedFileId,
  onSelectFile,
  onUploadCustomFile,
  onToggleCollapse,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const parsedFile = analyzeCodeFile(file.name, content, `src/${file.name}`);
      if (onUploadCustomFile) {
        onUploadCustomFile(parsedFile);
      }
    };
    reader.readAsText(file);
  };

  const handleCopyPath = (e: React.MouseEvent, path: string, id: string) => {
    e.stopPropagation();
    navigator.clipboard.writeText(path);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const filteredFiles = files.filter(f => 
    f.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
    f.path.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="w-full h-full bg-[#11131c] flex flex-col select-none text-xs flex-shrink-0">
      
      {/* Hidden file input */}
      <input 
        type="file" 
        ref={fileInputRef} 
        onChange={handleFileUpload} 
        accept=".py,.js,.ts,.tsx,.jsx,.java,.go,.rs,.cpp,.c,.json,.sql"
        className="hidden" 
      />

      {/* Explorer Header */}
      <div className="h-10 px-3.5 flex items-center justify-between border-b border-[#232638] text-[#94a3b8] font-medium text-xs bg-[#0e1017]">
        <div className="flex items-center space-x-2 text-white">
          <Layers className="w-3.5 h-3.5 text-indigo-400" />
          <span className="font-semibold text-xs tracking-tight">WORKSPACE EXPLORER</span>
        </div>
        
        <div className="flex items-center space-x-1">
          {files.length > 0 && (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="p-1 text-[#94a3b8] hover:text-white hover:bg-[#1c2030] rounded-lg transition-colors cursor-pointer"
              title="Add File to Workspace"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          )}

          {onToggleCollapse && (
            <button
              onClick={onToggleCollapse}
              className="p-1 text-[#94a3b8] hover:text-white hover:bg-[#1c2030] rounded-lg transition-colors cursor-pointer"
              title="Collapse Sidebar"
            >
              <PanelLeftClose className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* File Search Input (shown if multiple files exist) */}
      {files.length > 1 && (
        <div className="p-2 border-b border-[#232638]">
          <div className="relative">
            <Search className="w-3 h-3 text-[#64748b] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search files..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#0c0d14] border border-[#232638] text-white pl-7 pr-3 py-1 rounded-lg text-[11px] placeholder-[#64748b] focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>
        </div>
      )}

      {/* Directory Folder Tree */}
      <div className="p-1.5 overflow-y-auto flex-1 space-y-0.5">
        {filteredFiles.length > 0 ? (
          <>
            <div className="flex items-center justify-between text-[#64748b] py-1 px-2 font-semibold text-[10px] uppercase tracking-wider">
              <div className="flex items-center space-x-1.5">
                <ChevronDown className="w-3 h-3 text-[#64748b]" />
                <Folder className="w-3.5 h-3.5 text-indigo-400" />
                <span>Source Files</span>
              </div>
              <span className="text-[10px] text-[#64748b]">{filteredFiles.length}</span>
            </div>

            <div className="space-y-0.5 pt-0.5">
              {filteredFiles.map((file) => {
                const isSelected = selectedFileId === file.id;
                return (
                  <button
                    key={file.id}
                    onClick={() => onSelectFile(file)}
                    className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg transition-all duration-150 text-left cursor-pointer group relative ${
                      isSelected
                        ? 'bg-indigo-600/15 text-white border-l-2 border-indigo-500 shadow-sm'
                        : 'text-[#94a3b8] hover:bg-[#181a26] hover:text-white border-l-2 border-transparent'
                    }`}
                  >
                    <div className="flex items-center space-x-2 truncate min-w-0">
                      <FileCode className={`w-3.5 h-3.5 flex-shrink-0 ${
                        isSelected ? 'text-indigo-400' : 'text-[#64748b] group-hover:text-[#94a3b8]'
                      }`} />
                      <div className="truncate">
                        <div className="truncate font-medium text-xs text-white">{file.name}</div>
                        <div className="truncate text-[10px] text-[#64748b] font-mono">{file.path}</div>
                      </div>
                    </div>

                    {/* Standardized Status Badges & Quick Action */}
                    <div className="flex items-center space-x-1.5 flex-shrink-0 pl-1.5">
                      {/* Copy Path Icon on Hover */}
                      <button
                        onClick={(e) => handleCopyPath(e, file.path, file.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-[#64748b] hover:text-white rounded transition-opacity"
                        title="Copy file path"
                      >
                        {copiedId === file.id ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                      </button>

                      {file.hasSecurityRisk && (
                        <span 
                          title="Security Risk: OWASP Vulnerability Detected" 
                          className="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-300 border border-rose-500/30 text-[9px] font-semibold flex items-center space-x-1"
                        >
                          <ShieldAlert className="w-2.5 h-2.5 text-rose-400" />
                          <span>RISK</span>
                        </span>
                      )}
                      {file.hasBug && !file.hasSecurityRisk && (
                        <span 
                          title="AST Issue: Bug Detected" 
                          className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30 text-[9px] font-semibold flex items-center space-x-1"
                        >
                          <Bug className="w-2.5 h-2.5 text-amber-400" />
                          <span>BUG</span>
                        </span>
                      )}
                      {!file.hasBug && !file.hasSecurityRisk && (
                        <span 
                          title="Clean Code" 
                          className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 text-[9px] font-semibold flex items-center space-x-1"
                        >
                          <CheckCircle2 className="w-2.5 h-2.5 text-emerald-400" />
                          <span>PASS</span>
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        ) : (
          <div className="p-4 text-center space-y-2 my-auto">
            <div className="w-8 h-8 rounded-xl bg-[#181a26] border border-[#232638] flex items-center justify-center text-indigo-400 mx-auto">
              <FolderPlus className="w-4 h-4" />
            </div>
            <div>
              <div className="font-semibold text-white text-xs">No Files Open</div>
              <p className="text-[11px] text-[#64748b] mt-1 leading-relaxed">
                Open a code file or repository to start.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Footer Status */}
      <div className="p-2.5 border-t border-[#232638] bg-[#0c0d14] text-[10px] text-[#64748b] flex items-center justify-between font-mono">
        <span className="flex items-center space-x-1.5 text-[#94a3b8]">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
          <span>AST Grounding</span>
        </span>
        <span className="text-indigo-400">Ready</span>
      </div>

    </div>
  );
};
