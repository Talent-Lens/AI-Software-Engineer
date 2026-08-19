import { 
  ShieldCheck, 
  Cpu, 
  HelpCircle, 
  BarChart3,
  CheckCircle2,
  Sparkles,
  MessageSquareCode
} from 'lucide-react';

interface HeaderProps {
  activeModel: string;
  setActiveModel: (model: string) => void;
  isBackendConnected: boolean;
  isExecuting: boolean;
  onRunPipeline: () => void;
  selectedFileName?: string;
  activeView?: 'workspace' | 'eval';
  onSelectView?: (view: 'workspace' | 'eval') => void;
  onOpenGuide?: () => void;
  isChatOpen?: boolean;
  onToggleChat?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  activeModel,
  setActiveModel,
  isBackendConnected,
  isExecuting,
  onRunPipeline,
  selectedFileName,
  activeView = 'workspace',
  onSelectView,
  onOpenGuide,
  isChatOpen,
  onToggleChat,
}) => {

  return (
    <header className="bg-[#11131c] border-b border-[#232638] px-4 md:px-6 h-14 flex items-center justify-between z-30 select-none shadow-sm">
      {/* Left Brand Identity */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-teal-400 flex items-center justify-center text-white shadow-md shadow-indigo-950/50">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-white text-base tracking-tight">
                CodeGuardian
              </span>
              <span className="text-[10px] bg-indigo-500/10 text-indigo-300 font-medium px-2 py-0.5 rounded-full border border-indigo-500/20">
                Security & Verification
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Center / Right Section Navigation & Actions */}
      <div className="flex items-center space-x-3">
        
        {/* Workspace vs Benchmark View Switcher */}
        <div className="flex items-center bg-[#181a26] p-1 rounded-xl border border-[#262a3d] text-xs">
          <button
            onClick={() => onSelectView && onSelectView('workspace')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center space-x-1.5 ${
              activeView === 'workspace'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-[#94a3b8] hover:text-white'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Code Review</span>
          </button>
          
          <button
            onClick={() => onSelectView && onSelectView('eval')}
            className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center space-x-1.5 ${
              activeView === 'eval'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-[#94a3b8] hover:text-white'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Benchmarks</span>
          </button>
        </div>

        {/* AI Model Selector */}
        <div className="hidden sm:flex items-center space-x-2 bg-[#181a26] px-3 py-1.5 rounded-xl border border-[#262a3d] text-xs text-[#cbd5e1]">
          <Cpu className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
          <select
            value={activeModel}
            onChange={(e) => setActiveModel(e.target.value)}
            className="bg-transparent text-white text-xs focus:outline-none cursor-pointer pr-1 font-medium"
          >
            <option value="qwen-2.5-coder-32b" className="bg-[#181a26] text-white">Qwen-2.5 Coder (32B)</option>
            <option value="deepseek-r1-7b" className="bg-[#181a26] text-white">DeepSeek-R1 (7B)</option>
            <option value="gemini-2.5-flash" className="bg-[#181a26] text-white">Gemini 2.5 Flash</option>
          </select>
        </div>

        {/* Ask AI (Q&A) Toggle Button */}
        {onToggleChat && (
          <button
            onClick={onToggleChat}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer shadow-sm ${
              isChatOpen
                ? 'bg-indigo-600 border-indigo-400 text-white shadow-indigo-950/50'
                : 'bg-[#1c2030] hover:bg-[#252a40] border-[#2d334d] text-indigo-200 hover:text-white'
            }`}
            title="Ask Questions About the Code (Qwen-2.5 Coder 32B)"
          >
            <MessageSquareCode className="w-3.5 h-3.5 text-indigo-400" />
            <span>Ask AI</span>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          </button>
        )}

        {/* How It Works / Onboarding Guide Button */}
        {onOpenGuide && (
          <button
            onClick={onOpenGuide}
            className="flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl bg-[#1c2030] hover:bg-[#252a40] border border-[#2d334d] text-indigo-200 hover:text-white text-xs font-semibold transition-all cursor-pointer shadow-sm hover:border-indigo-400/50"
            title="Learn how CodeGuardian works and view scope"
          >
            <HelpCircle className="w-3.5 h-3.5 text-indigo-400" />
            <span>How It Works</span>
          </button>
        )}


      </div>
    </header>
  );
};
