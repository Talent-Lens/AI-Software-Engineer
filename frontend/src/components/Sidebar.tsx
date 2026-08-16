import React from 'react';
import { 
  Files, 
  GitFork, 
  GitCompare, 
  BarChart3, 
  Settings, 
  ShieldCheck, 
  CheckCircle2 
} from 'lucide-react';
import { ActiveTab } from '../types';

interface SidebarProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  nodeCount: number;
  evalCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  nodeCount,
  evalCount,
}) => {
  const tabs = [
    {
      id: 'diff' as ActiveTab,
      label: 'Code & AST Workbench',
      icon: GitCompare,
      badge: 'Interactive Diff',
    },
    {
      id: 'langgraph' as ActiveTab,
      label: 'LangGraph Multi-Agent Canvas',
      icon: GitFork,
      badge: `${nodeCount} Agents`,
    },
    {
      id: 'eval' as ActiveTab,
      label: 'RAG Triad & Eval Suite',
      icon: BarChart3,
      badge: `${evalCount} Benchmarks`,
    },
    {
      id: 'settings' as ActiveTab,
      label: 'Platform Settings & Config',
      icon: Settings,
      badge: null,
    },
  ];

  return (
    <aside className="w-14 bg-[#0e0e15] border-r border-[#252536] flex flex-col justify-between items-center py-3 select-none z-10">
      {/* Top Activity Bar Navigation */}
      <div className="flex flex-col items-center space-y-2.5 w-full">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              title={tab.label}
              className={`relative group w-10 h-10 flex items-center justify-center rounded-xl transition-all duration-200 cursor-pointer ${
                isActive
                  ? 'bg-teal-950/70 text-teal-300 border border-teal-500/40 shadow-lg shadow-teal-950/50 ring-1 ring-teal-500/30'
                  : 'text-[#787890] hover:text-white hover:bg-[#181824]'
              }`}
            >
              <Icon className={`w-5 h-5 ${isActive ? 'text-teal-300' : ''}`} />
              
              {/* Tooltip on hover */}
              <div className="absolute left-14 bg-[#14141d] text-white text-[11px] px-3 py-1.5 rounded-xl border border-[#252536] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-2xl z-50 font-mono">
                {tab.label}
                {tab.badge && (
                  <span className="ml-2 bg-teal-500/20 text-teal-300 border border-teal-500/30 px-1.5 py-0.5 rounded text-[10px] font-mono">
                    {tab.badge}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Bottom Status / Guardrail Badge */}
      <div className="flex flex-col items-center space-y-3 pb-1">
        <div className="group relative">
          <div className="w-9 h-9 rounded-xl bg-teal-500/10 border border-teal-500/30 flex items-center justify-center text-teal-400 cursor-pointer shadow-md">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div className="absolute left-14 bottom-0 bg-[#14141d] text-white text-[11px] px-3 py-2 rounded-xl border border-[#252536] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-2xl z-50 font-mono">
            <div className="font-bold text-teal-300">CodeGuardian Guardrail</div>
            <div className="text-[10px] text-[#787890]">Tree-Sitter AST & SAST Active</div>
          </div>
        </div>
      </div>
    </aside>
  );
};
