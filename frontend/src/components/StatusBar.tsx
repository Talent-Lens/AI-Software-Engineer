import React from 'react';
import { 
  GitBranch, 
  AlertCircle, 
  Check, 
  Terminal, 
  Cpu, 
  Clock, 
  Database,
  Activity
} from 'lucide-react';
import { CodeFile } from '../types';

interface StatusBarProps {
  selectedFile: CodeFile;
  isExecuting: boolean;
  activeNodeName?: string;
  isBackendConnected: boolean;
  totalExecutionMs?: number;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  selectedFile,
  isExecuting,
  activeNodeName,
  isBackendConnected,
  totalExecutionMs = 420,
}) => {
  return (
    <footer className="h-6 bg-[#0a0a0e] text-[#8e8ea6] border-t border-[#252536] flex items-center justify-between px-3 text-[11px] font-mono select-none z-30">
      {/* Left status items */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-1.5 hover:text-white px-1.5 py-0.5 rounded cursor-pointer">
          <GitBranch className="w-3 h-3 text-teal-400" />
          <span>main*</span>
        </div>

        <div className="flex items-center space-x-1">
          <Check className="w-3 h-3 text-emerald-400" />
          <span className="text-emerald-300">0 syntax errors</span>
        </div>

        {isExecuting && (
          <div className="flex items-center space-x-1.5 bg-teal-950/60 border border-teal-500/40 px-2 py-0.5 rounded animate-pulse">
            <Activity className="w-3 h-3 text-teal-400 animate-spin" />
            <span className="text-teal-200">Executing Node: <strong className="text-white">{activeNodeName || 'Running...'}</strong></span>
          </div>
        )}
      </div>

      {/* Right status items */}
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-1 hover:text-white px-1.5 py-0.5 rounded cursor-pointer">
          <Clock className="w-3 h-3 text-teal-400" />
          <span>Latency: {totalExecutionMs}ms</span>
        </div>

        <div className="flex items-center space-x-1 hover:text-white px-1.5 py-0.5 rounded cursor-pointer">
          <Database className="w-3 h-3 text-cyan-400" />
          <span>ChromaDB Vector Store</span>
        </div>

        <div className="flex items-center space-x-1 hover:text-white px-1.5 py-0.5 rounded cursor-pointer">
          <span>{selectedFile.language.toUpperCase()}</span>
        </div>

        <div className="flex items-center space-x-1.5 bg-[#14141d] px-2 py-0.5 rounded border border-[#252536]">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span className="text-white">UTF-8</span>
        </div>
      </div>
    </footer>
  );
};
