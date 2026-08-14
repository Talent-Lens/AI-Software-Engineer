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
      id: 'explorer' as ActiveTab,
      label: 'Explorer & AST Files',
      icon: Files,
      badge: null,
    },
    {
      id: 'langgraph' as ActiveTab,
      label: 'Live LangGraph Canvas',
      icon: GitFork,
      badge: `${nodeCount} Nodes`,
    },
    {
      id: 'diff' as ActiveTab,
      label: 'Monaco Diff & Fix Viewer',
      icon: GitCompare,
      badge: 'PR View',
    },
    {
      id: 'eval' as ActiveTab,
      label: 'Recharts Evaluation Suite',
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
    <aside className="w-14 bg-[#333333] border-r border-[#3c3c3c] flex flex-col justify-between items-center py-2 select-none z-10">
      {/* Top Activity Bar Navigation */}
      <div className="flex flex-col items-center space-y-2 w-full">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              title={tab.label}
              className={`relative group w-12 h-12 flex items-center justify-center rounded-lg transition-all duration-150 ${
                isActive
                  ? 'bg-[#252526] text-[#007acc] border-l-2 border-[#007acc]'
                  : 'text-[#858585] hover:text-white hover:bg-[#2a2d2e]'
              }`}
            >
              <Icon className={`w-5 h-5 ${isActive ? 'text-[#007acc]' : ''}`} />
              
              {/* Tooltip on hover */}
              <div className="absolute left-14 bg-[#252526] text-white text-[11px] px-2.5 py-1 rounded border border-[#3c3c3c] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-lg z-50">
                {tab.label}
                {tab.badge && (
                  <span className="ml-2 bg-[#007acc]/30 text-[#60a5fa] px-1.5 py-0.5 rounded text-[10px] font-mono">
                    {tab.badge}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Bottom Status / Guardrail Badge */}
      <div className="flex flex-col items-center space-y-3 pb-2">
        <div className="group relative">
          <div className="w-9 h-9 rounded-full bg-emerald-950/60 border border-emerald-700/60 flex items-center justify-center text-emerald-400 cursor-pointer">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div className="absolute left-14 bottom-0 bg-[#252526] text-white text-[11px] px-2.5 py-1 rounded border border-[#3c3c3c] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity shadow-lg z-50">
            <div className="font-semibold text-emerald-400">AST Line & SAST Guardrail</div>
            <div className="text-[10px] text-[#858585]">100% Syntax & Citation Grounding</div>
          </div>
        </div>
      </div>
    </aside>
  );
};
