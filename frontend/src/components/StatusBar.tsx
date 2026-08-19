import React from 'react';
import { 
  GitBranch, 
  Check, 
  Clock, 
  Database,
  Activity,
  ShieldCheck,
  MessageSquareCode
} from 'lucide-react';
import { CodeFile } from '../types';

interface StatusBarProps {
  selectedFile: CodeFile;
  isExecuting: boolean;
  activeNodeName?: string;
  isBackendConnected: boolean;
  totalExecutionMs?: number;
  isChatOpen?: boolean;
  onToggleChat?: () => void;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  selectedFile,
  isExecuting,
  activeNodeName,
  isBackendConnected,
  totalExecutionMs = 415,
  isChatOpen,
  onToggleChat,
}) => {
  return (
    <footer className="h-6 bg-[#0e1017] text-[#94a3b8] border-t border-[#232638] flex items-center justify-between px-3 text-[11px] select-none z-30 font-mono">
      {/* Left status items */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-1.5 hover:text-white px-1.5 py-0.5 rounded cursor-pointer transition-colors">
          <GitBranch className="w-3 h-3 text-indigo-400" />
          <span>main</span>
        </div>

        <div className="flex items-center space-x-1 text-emerald-400">
          <Check className="w-3 h-3" />
          <span>AST Verified (0 Errors)</span>
        </div>

        {onToggleChat && (
          <button
            onClick={onToggleChat}
            className="flex items-center space-x-1 text-indigo-300 hover:text-white px-2 py-0.5 rounded hover:bg-[#1c2030] cursor-pointer transition-colors"
            title="Toggle Code Q&A Assistant"
          >
            <MessageSquareCode className="w-3 h-3 text-indigo-400" />
            <span>Ask Qwen (32B)</span>
          </button>
        )}

        {isExecuting && (
          <div className="flex items-center space-x-1.5 bg-indigo-950/60 border border-indigo-500/40 px-2 py-0.5 rounded text-indigo-200">
            <Activity className="w-3 h-3 text-indigo-400 animate-spin" />
            <span>Executing: <strong className="text-white">{activeNodeName || 'Running...'}</strong></span>
          </div>
        )}
      </div>


      {/* Right status items */}
      <div className="flex items-center space-x-4">
        <div className="hidden sm:flex items-center space-x-1 hover:text-white px-1 py-0.5 rounded cursor-pointer">
          <Clock className="w-3 h-3 text-indigo-400" />
          <span>{totalExecutionMs}ms</span>
        </div>

        <div className="hidden md:flex items-center space-x-1 hover:text-white px-1 py-0.5 rounded cursor-pointer">
          <Database className="w-3 h-3 text-teal-400" />
          <span>ChromaDB RRF</span>
        </div>

        <div className="flex items-center space-x-1 text-[#cbd5e1]">
          <span>{selectedFile.language ? selectedFile.language.toUpperCase() : 'PYTHON'}</span>
        </div>

        <div className="flex items-center space-x-1.5 bg-[#151722] px-2 py-0.5 rounded border border-[#232638] text-[10px]">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          <span className="text-white">UTF-8</span>
        </div>
      </div>
    </footer>
  );
};
