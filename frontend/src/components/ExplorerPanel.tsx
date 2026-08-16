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
  AlertCircle
} from 'lucide-react';
import { CodeFile } from '../types';

interface ExplorerPanelProps {
  files: CodeFile[];
  selectedFileId: string;
  onSelectFile: (file: CodeFile) => void;
  onUploadCustomFile?: (newFile: CodeFile) => void;
  onClearFile?: () => void;
}

export const ExplorerPanel: React.FC<ExplorerPanelProps> = ({
  files,
  selectedFileId,
  onSelectFile,
  onUploadCustomFile,
  onClearFile,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
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

  const filteredFiles = files.filter(f => 
    f.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
    f.path.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="w-full md:w-64 bg-[#0c0c14] border-b md:border-b-0 md:border-r border-[#202030] flex flex-col max-h-48 md:max-h-none h-full select-none text-xs flex-shrink-0 overflow-y-auto">
      {/* Hidden file input */}
      <input 
        type="file" 
        ref={fileInputRef} 
        onChange={handleFileUpload} 
        accept=".py,.js,.ts,.tsx,.jsx,.java,.go,.rs,.cpp,.c,.json,.sql"
        className="hidden" 
      />

      {/* Explorer Header */}
      <div className="h-11 px-3.5 flex items-center justify-between border-b border-[#202030] text-[#8e8ea6] font-semibold text-[11px] font-mono">
        <div className="flex items-center space-x-1.5 text-white">
          <Layers className="w-4 h-4 text-teal-400" />
          <span className="tracking-wide">WORKSPACE</span>
        </div>
        {files.length > 0 && (
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center space-x-1 bg-[#181826] hover:bg-teal-950/60 hover:text-teal-300 border border-[#2c2c3e] hover:border-teal-500/40 text-[#a0a0b8] px-2 py-0.5 rounded-lg text-[11px] font-medium font-mono transition-all cursor-pointer"
            title="Add File to Workspace"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add</span>
          </button>
        )}
      </div>

      {/* File Search Input (only shown if files exist) */}
      {files.length > 0 && (
        <div className="p-2.5 border-b border-[#202030]">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[#65657d] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Filter files..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#12121c] border border-[#202030] text-white pl-8 pr-3 py-1.5 rounded-lg text-[11px] font-mono placeholder-[#55556d] focus:outline-none focus:border-teal-500/60 transition-colors"
            />
          </div>
        </div>
      )}

      {/* Directory Folder Tree */}
      <div className="p-2 overflow-y-auto flex-1 space-y-1">
        {filteredFiles.length > 0 ? (
          <>
            <div className="flex items-center justify-between text-[#7d7d95] py-1 px-1.5 font-bold font-mono text-[10px] uppercase tracking-wider">
              <div className="flex items-center space-x-1.5">
                <ChevronDown className="w-3.5 h-3.5 text-[#65657d]" />
                <Folder className="w-3.5 h-3.5 text-teal-400" />
                <span className="text-[#a0a0b8]">Open Modules</span>
              </div>
              <span className="text-[10px] text-[#65657d]">{filteredFiles.length}</span>
            </div>

            <div className="space-y-0.5 pt-0.5">
              {filteredFiles.map((file) => {
                const isSelected = selectedFileId === file.id;
                return (
                  <button
                    key={file.id}
                    onClick={() => onSelectFile(file)}
                    className={`w-full flex items-center justify-between px-2.5 py-2 rounded-xl transition-all duration-150 text-left cursor-pointer group ${
                      isSelected
                        ? 'bg-teal-950/60 text-white border border-teal-500/40 shadow-sm ring-1 ring-teal-500/20 font-medium'
                        : 'text-[#a0a0b8] hover:bg-[#141420] hover:text-white border border-transparent'
                    }`}
                  >
                    <div className="flex items-center space-x-2 truncate min-w-0">
                      <FileCode className={`w-3.5 h-3.5 flex-shrink-0 ${
                        isSelected ? 'text-teal-400' :
                        file.language === 'python' ? 'text-teal-500/80' :
                        file.language === 'typescript' ? 'text-blue-400/80' : 'text-emerald-400/80'
                      }`} />
                      <div className="truncate">
                        <div className="truncate font-mono text-[11px]">{file.name}</div>
                        <div className="truncate text-[9px] text-[#606078] font-mono">{file.path}</div>
                      </div>
                    </div>

                    {/* Status Indicator */}
                    <div className="flex items-center space-x-1.5 flex-shrink-0 pl-1">
                      {file.hasSecurityRisk && (
                        <div 
                          title="Security Risk: OWASP Vulnerability Detected" 
                          className="flex items-center space-x-1 px-1.5 py-0.5 rounded-md bg-rose-950/50 text-rose-300 border border-rose-500/30 text-[9px] font-mono"
                        >
                          <ShieldAlert className="w-2.5 h-2.5 text-rose-400" />
                          <span>RISK</span>
                        </div>
                      )}
                      {file.hasBug && !file.hasSecurityRisk && (
                        <div 
                          title="AST Issue: Bug Detected" 
                          className="flex items-center space-x-1 px-1.5 py-0.5 rounded-md bg-amber-950/50 text-amber-300 border border-amber-500/30 text-[9px] font-mono"
                        >
                          <Bug className="w-2.5 h-2.5 text-amber-400" />
                          <span>BUG</span>
                        </div>
                      )}
                      {!file.hasBug && !file.hasSecurityRisk && (
                        <div 
                          title="Clean Code" 
                          className="flex items-center space-x-1 px-1.5 py-0.5 rounded-md bg-emerald-950/40 text-emerald-300 border border-emerald-500/30 text-[9px] font-mono"
                        >
                          <CheckCircle2 className="w-2.5 h-2.5 text-emerald-400" />
                          <span>PASS</span>
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        ) : (
          /* Clean Quiet Empty State (Zero duplicate buttons) */
          <div className="p-4 text-center space-y-2 my-auto">
            <div className="w-8 h-8 rounded-xl bg-[#141420] border border-[#202030] flex items-center justify-center text-teal-400 mx-auto">
              <FolderPlus className="w-4 h-4" />
            </div>
            <div>
              <div className="font-bold text-white text-xs font-mono">No Files Open</div>
              <p className="text-[10px] text-[#65657d] mt-1 leading-relaxed">
                Open a code file or index a repository to begin analysis.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Footer Info Box */}
      <div className="p-3 border-t border-[#202030] bg-[#090910] text-[10px] text-[#65657d] flex items-center justify-between font-mono">
        <span className="flex items-center space-x-1 text-[#8b8ba0]">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
          <span>AST Tree-Sitter</span>
        </span>
        <span className="text-teal-400/80">Active</span>
      </div>
    </div>
  );
};
