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
    <footer className="h-6 bg-[#007acc] text-white flex items-center justify-between px-3 text-[11px] font-mono select-none z-30">
      {/* Left status items */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-1 hover:bg-[#005999] px-1.5 py-0.5 rounded cursor-pointer">
          <GitBranch className="w-3 h-3" />
          <span>frontend*</span>
        </div>

        <div className="flex items-center space-x-1">
          <Check className="w-3 h-3 text-emerald-300" />
          <span>0 errors, 0 warnings</span>
        </div>

        {isExecuting && (
          <div className="flex items-center space-x-1.5 bg-[#005999] px-2 py-0.5 rounded animate-pulse">
            <Activity className="w-3 h-3 text-amber-300 animate-spin" />
            <span>Node: <strong className="text-yellow-200">{activeNodeName || 'Running...'}</strong></span>
          </div>
        )}
      </div>

      {/* Right status items */}
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-1 hover:bg-[#005999] px-1.5 py-0.5 rounded cursor-pointer">
          <Clock className="w-3 h-3 text-blue-200" />
          <span>Pipeline Latency: {totalExecutionMs}ms</span>
        </div>

        <div className="flex items-center space-x-1 hover:bg-[#005999] px-1.5 py-0.5 rounded cursor-pointer">
          <Database className="w-3 h-3 text-cyan-200" />
          <span>ChromaDB Vector + BM25</span>
        </div>

        <div className="flex items-center space-x-1 hover:bg-[#005999] px-1.5 py-0.5 rounded cursor-pointer">
          <span>{selectedFile.language.toUpperCase()}</span>
        </div>

        <div className="flex items-center space-x-1 bg-[#005999] px-1.5 py-0.5 rounded">
          <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
          <span>UTF-8</span>
        </div>
      </div>
    </footer>
  );
};
