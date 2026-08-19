import React, { useState, useEffect, useRef } from 'react';
import { 
  Bot, 
  User, 
  Send, 
  Sparkles, 
  X, 
  RotateCcw, 
  Copy, 
  Check, 
  ChevronRight, 
  AlertCircle, 
  Loader2, 
  Cpu, 
  ArrowUpRight, 
  ShieldAlert, 
  HelpCircle,
  MessageSquareCode,
  CornerDownLeft,
  Maximize2,
  Minimize2,
  Trash2
} from 'lucide-react';
import { CodeFile } from '../types';
import { sendCodeChatMessage, ChatResponsePayload } from '../services/api';

export interface ChatMessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  lineReferences?: number[];
  modelUsed?: string;
  providerUsed?: string;
  isError?: boolean;
}

interface CodeChatPanelProps {
  currentFile?: CodeFile | null;
  isOpen: boolean;
  onClose: () => void;
  onJumpToLine: (lineNumber: number) => void;
  activeModel?: string;
  onModelChange?: (model: string) => void;
  layoutMode?: 'right-dock' | 'bottom-drawer';
}

const QUICK_STARTER_PROMPTS = [
  { label: 'Why is this flagged as a risk?', icon: ShieldAlert, prompt: 'Why is this flagged as a risk? Explain the vulnerability and attack vector.' },
  { label: 'Explain this fix', icon: Sparkles, prompt: 'Explain the proposed fix and how it resolves the issue.' },
  { label: 'What does this function do?', icon: HelpCircle, prompt: 'What does this code do? Provide a high-level summary and breakdown.' },
  { label: 'Check for edge cases', icon: AlertCircle, prompt: 'Are there any potential edge cases, null checks, or performance bottlenecks in this code?' },
];

export const CodeChatPanel: React.FC<CodeChatPanelProps> = ({
  currentFile,
  isOpen,
  onClose,
  onJumpToLine,
  activeModel = 'qwen-2.5-coder-32b',
  onModelChange,
  layoutMode = 'right-dock',
}) => {
  // Store chat history per file ID so switching files preserves conversation
  const [chatHistoryByFile, setChatHistoryByFile] = useState<Record<string, ChatMessageItem[]>>({});
  const [inputText, setInputText] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);

  const fileKey = currentFile?.id || currentFile?.path || 'global-session';
  const messages = chatHistoryByFile[fileKey] || [];

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom of chat
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen, isLoading]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [isOpen, fileKey]);

  // Set default initial welcome message for new files if empty
  useEffect(() => {
    if (currentFile && (!chatHistoryByFile[fileKey] || chatHistoryByFile[fileKey].length === 0)) {
      const initialGreeting: ChatMessageItem = {
        id: `welcome-${fileKey}`,
        role: 'assistant',
        content: `👋 **CodeGuardian Q&A Assistant** is ready for \`${currentFile.name}\`.\n\n` +
          `I have full context on the original code, proposed fix, and AST security audit findings.\n\n` +
          `Ask me anything or pick a quick prompt below:`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        modelUsed: activeModel,
        providerUsed: 'codeguardian-engine'
      };

      setChatHistoryByFile(prev => ({
        ...prev,
        [fileKey]: [initialGreeting]
      }));
    }
  }, [currentFile?.id, fileKey]);

  const handleSendMessage = async (questionText?: string) => {
    const query = (questionText || inputText).trim();
    if (!query || isLoading) return;

    const userMessage: ChatMessageItem = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    // Update conversation state with user prompt
    const updatedMessages = [...messages, userMessage];
    setChatHistoryByFile(prev => ({
      ...prev,
      [fileKey]: updatedMessages
    }));

    setInputText('');
    setIsLoading(true);
    setLastFailedQuestion(null);

    try {
      // Build API request with conversation history context
      const historyForApi = updatedMessages.map(m => ({
        role: m.role,
        content: m.content
      }));

      const res: ChatResponsePayload = await sendCodeChatMessage({
        question: query,
        filepath: currentFile?.path || currentFile?.name,
        file_code: currentFile?.originalCode,
        proposed_fix: currentFile?.proposedFix,
        security_findings: currentFile?.securityIssues || [],
        history: historyForApi,
        model: activeModel,
      });

      const assistantMessage: ChatMessageItem = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: res.answer,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        lineReferences: res.line_references,
        modelUsed: res.model_used,
        providerUsed: res.provider_used,
      };

      setChatHistoryByFile(prev => ({
        ...prev,
        [fileKey]: [...(prev[fileKey] || []), assistantMessage]
      }));
    } catch (err: any) {
      setLastFailedQuestion(query);
      const errorMessage: ChatMessageItem = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: `⚠️ **Unable to complete request.** Error: ${err.message || 'Model connection timeout'}. Please check your connection and retry.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        isError: true,
      };

      setChatHistoryByFile(prev => ({
        ...prev,
        [fileKey]: [...(prev[fileKey] || []), errorMessage]
      }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearHistory = () => {
    setChatHistoryByFile(prev => ({
      ...prev,
      [fileKey]: []
    }));
  };

  const handleCopyMessage = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedMsgId(id);
    setTimeout(() => setCopiedMsgId(null), 1800);
  };

  // Helper to parse inline formatting (bold, code, and line numbers)
  const formatInlineText = (text: string) => {
    // Regex matches:
    // 1. [Line 28] or Line 28
    // 2. `code`
    // 3. **bold**
    // 4. *italic*
    const inlineRegex = /(\[(?:Line|line)\s*(\d+)\]|(?:\b(?:Line|line)\s*(\d+)\b))|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)/g;
    const elements: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = inlineRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        elements.push(text.substring(lastIndex, match.index));
      }

      const [fullMatch, , lineNum1, lineNum2, codeMatch, boldMatch, italicMatch] = match;
      const lineNumStr = lineNum1 || lineNum2;

      if (lineNumStr) {
        const lineNum = parseInt(lineNumStr, 10);
        elements.push(
          <button
            key={`line-${match.index}-${lineNum}`}
            onClick={() => onJumpToLine(lineNum)}
            className="inline-flex items-center space-x-0.5 px-1.5 py-0.5 mx-0.5 rounded-md bg-indigo-950/80 hover:bg-indigo-600 text-indigo-300 hover:text-white border border-indigo-500/40 text-[10px] font-mono font-semibold transition-colors cursor-pointer shadow-xs"
            title={`Click to navigate to Line #${lineNum}`}
          >
            <span>Line #{lineNum}</span>
            <ArrowUpRight className="w-2.5 h-2.5 opacity-80" />
          </button>
        );
      } else if (codeMatch) {
        const codeContent = codeMatch.slice(1, -1);
        elements.push(
          <code
            key={`code-${match.index}`}
            className="px-1.5 py-0.5 mx-0.5 rounded bg-[#1c2032] border border-indigo-500/20 text-indigo-300 font-mono text-[11px]"
          >
            {codeContent}
          </code>
        );
      } else if (boldMatch) {
        const boldContent = boldMatch.slice(2, -2);
        elements.push(
          <strong key={`bold-${match.index}`} className="text-white font-semibold">
            {boldContent}
          </strong>
        );
      } else if (italicMatch) {
        const italicContent = italicMatch.slice(1, -1);
        elements.push(
          <em key={`italic-${match.index}`} className="text-slate-300 italic">
            {italicContent}
          </em>
        );
      }

      lastIndex = match.index + fullMatch.length;
    }

    if (lastIndex < text.length) {
      elements.push(text.substring(lastIndex));
    }

    return elements;
  };

  // Helper to render markdown text with code blocks, headings, lists, and line citations
  const renderMessageContent = (content: string, lineRefs?: number[]) => {
    // Parse code blocks first
    const parts = content.split(/(```[\s\S]*?```)/g);

    return (
      <div className="space-y-2 text-xs text-[#cbd5e1] leading-relaxed select-text">
        {parts.map((part, partIdx) => {
          if (part.startsWith('```') && part.endsWith('```')) {
            const lines = part.slice(3, -3).split('\n');
            const lang = lines[0]?.trim() || 'code';
            const codeBody = lines.slice(1).join('\n') || lines[0] || '';

            return (
              <div key={partIdx} className="my-2 rounded-xl bg-[#0c0e17] border border-[#262a3d] overflow-hidden shadow-inner">
                <div className="px-3 py-1.5 bg-[#141724] border-b border-[#262a3d] flex items-center justify-between text-[10px] text-[#94a3b8]">
                  <span className="font-mono font-medium text-indigo-400">{lang}</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(codeBody)}
                    className="hover:text-white transition-colors cursor-pointer flex items-center space-x-1"
                    title="Copy code"
                  >
                    <Copy className="w-3 h-3" />
                    <span>Copy</span>
                  </button>
                </div>
                <pre className="p-3 text-[11px] font-mono text-emerald-300 overflow-x-auto leading-relaxed">
                  <code>{codeBody}</code>
                </pre>
              </div>
            );
          }

          // Handle regular markdown text lines
          const lines = part.split('\n');
          return (
            <div key={partIdx} className="space-y-1.5">
              {lines.map((line, idx) => {
                const trimmed = line.trim();
                if (!trimmed) return <div key={idx} className="h-1" />;

                if (trimmed.startsWith('### ')) {
                  return (
                    <h4 key={idx} className="text-white font-bold text-xs mt-2 mb-1">
                      {formatInlineText(trimmed.replace('### ', ''))}
                    </h4>
                  );
                }
                if (trimmed.startsWith('## ')) {
                  return (
                    <h3 key={idx} className="text-white font-bold text-sm mt-2.5 mb-1">
                      {formatInlineText(trimmed.replace('## ', ''))}
                    </h3>
                  );
                }
                if (trimmed.startsWith('# ')) {
                  return (
                    <h2 key={idx} className="text-white font-bold text-sm mt-3 mb-1">
                      {formatInlineText(trimmed.replace('# ', ''))}
                    </h2>
                  );
                }
                if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
                  return (
                    <div key={idx} className="flex items-start space-x-1.5 pl-1.5">
                      <span className="text-indigo-400 font-bold mt-0.5">•</span>
                      <div className="flex-1 min-w-0">{formatInlineText(trimmed.substring(2))}</div>
                    </div>
                  );
                }
                const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
                if (numMatch) {
                  return (
                    <div key={idx} className="flex items-start space-x-1.5 pl-1.5">
                      <span className="text-indigo-400 font-mono font-bold mt-0.5 text-[11px]">{numMatch[1]}.</span>
                      <div className="flex-1 min-w-0">{formatInlineText(numMatch[2])}</div>
                    </div>
                  );
                }
                return <p key={idx} className="leading-relaxed">{formatInlineText(line)}</p>;
              })}
            </div>
          );
        })}
      </div>
    );
  };

  if (!isOpen) return null;

  return (
    <div className={`flex flex-col bg-[#11131c] border-l border-[#232638] h-full shadow-2xl z-20 select-none animate-fadeIn ${
      layoutMode === 'right-dock' ? 'w-80 md:w-96 flex-shrink-0' : 'w-full h-80'
    }`}>
      
      {/* Header Bar */}
      <div className="p-3.5 border-b border-[#232638] bg-[#151722] flex items-center justify-between flex-shrink-0">
        <div className="flex items-center space-x-2 min-w-0">
          <div className="w-7 h-7 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <MessageSquareCode className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center space-x-1.5">
              <h3 className="font-bold text-white text-xs truncate">Code Q&A</h3>
              <select
                value={activeModel}
                onChange={(e) => onModelChange && onModelChange(e.target.value)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950/70 text-indigo-300 border border-indigo-500/30 font-medium cursor-pointer focus:outline-none focus:ring-1 focus:ring-indigo-400"
                title="Select reasoning model for Code Q&A"
              >
                <option value="qwen-2.5-coder-32b" className="bg-[#151722] text-white">Qwen-2.5 Coder (32B)</option>
                <option value="deepseek-r1-7b" className="bg-[#151722] text-white">DeepSeek-R1 (7B)</option>
                <option value="gemini-2.5-flash" className="bg-[#151722] text-white">Gemini 2.5 Flash</option>
              </select>
            </div>
            <p className="text-[10px] text-[#94a3b8] truncate">
              {currentFile ? currentFile.name : 'Context-aware LLM'}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-1">
          {messages.length > 0 && (
            <button
              onClick={handleClearHistory}
              className="p-1.5 text-[#94a3b8] hover:text-rose-300 hover:bg-[#1c2030] rounded-lg transition-colors cursor-pointer"
              title="Clear conversation"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 text-[#94a3b8] hover:text-white hover:bg-[#1c2030] rounded-lg transition-colors cursor-pointer"
            title="Close Q&A Panel"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages List Area */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3.5 text-xs">
        {messages.map((msg) => {
          const isAssistant = msg.role === 'assistant';
          return (
            <div
              key={msg.id}
              className={`flex flex-col space-y-1 ${isAssistant ? 'items-start' : 'items-end'}`}
            >
              {/* Sender & Timestamp */}
              <div className="flex items-center space-x-1.5 text-[10px] text-[#64748b] px-1">
                {isAssistant ? (
                  <>
                    <Bot className="w-3 h-3 text-indigo-400" />
                    <span className="text-[#94a3b8] font-medium">CodeGuardian</span>
                  </>
                ) : (
                  <>
                    <span className="text-[#94a3b8] font-medium">You</span>
                    <User className="w-3 h-3 text-indigo-300" />
                  </>
                )}
                <span>•</span>
                <span>{msg.timestamp}</span>
              </div>

              {/* Bubble Body */}
              <div className={`p-3 rounded-2xl max-w-[92%] relative group transition-all ${
                isAssistant
                  ? msg.isError
                    ? 'bg-rose-950/30 border border-rose-500/40 text-rose-200'
                    : 'bg-[#181a26] border border-[#262a3d] text-white shadow-sm'
                  : 'bg-indigo-600 text-white rounded-br-xs shadow-md'
              }`}>
                {renderMessageContent(msg.content, msg.lineReferences)}

                {/* Referenced Line Numbers Jump Pill Bar */}
                {isAssistant && msg.lineReferences && msg.lineReferences.length > 0 && (
                  <div className="mt-2.5 pt-2 border-t border-[#2a2e42] flex flex-wrap items-center gap-1.5">
                    <span className="text-[10px] text-[#94a3b8] flex items-center space-x-1">
                      <ArrowUpRight className="w-3 h-3 text-indigo-400" />
                      <span>Referenced lines:</span>
                    </span>
                    {msg.lineReferences.map((line) => (
                      <button
                        key={line}
                        onClick={() => onJumpToLine(line)}
                        className="px-2 py-0.5 rounded-md bg-indigo-500/20 hover:bg-indigo-600 text-indigo-300 hover:text-white border border-indigo-500/30 text-[10px] font-mono font-bold transition-all cursor-pointer shadow-xs"
                      >
                        Line #{line}
                      </button>
                    ))}
                  </div>
                )}

                {/* Copy Button */}
                <button
                  onClick={() => handleCopyMessage(msg.id, msg.content)}
                  className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 p-1 rounded-md bg-[#11131c]/80 hover:bg-[#11131c] text-[#94a3b8] hover:text-white transition-opacity cursor-pointer text-[10px]"
                  title="Copy answer"
                >
                  {copiedMsgId === msg.id ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                </button>
              </div>
            </div>
          );
        })}

        {/* Loading / Typing Indicator */}
        {isLoading && (
          <div className="flex flex-col items-start space-y-1 animate-fadeIn">
            <div className="flex items-center space-x-1.5 text-[10px] text-[#64748b] px-1">
              <Bot className="w-3 h-3 text-indigo-400" />
              <span className="text-[#94a3b8] font-medium">CodeGuardian is thinking...</span>
            </div>
            <div className="p-3.5 rounded-2xl bg-[#181a26] border border-[#262a3d] flex items-center space-x-2">
              <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin" />
              <span className="text-xs text-[#94a3b8]">Analyzing AST, diff, and security findings...</span>
            </div>
          </div>
        )}

        {/* Retry Button on Error */}
        {lastFailedQuestion && !isLoading && (
          <div className="p-2.5 rounded-xl bg-rose-950/20 border border-rose-500/30 flex items-center justify-between">
            <span className="text-[11px] text-rose-300">Request timed out or failed.</span>
            <button
              onClick={() => handleSendMessage(lastFailedQuestion)}
              className="px-2.5 py-1 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold cursor-pointer transition-colors flex items-center space-x-1"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Retry</span>
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Quick Starter Prompts */}
      <div className="px-3.5 py-2 border-t border-[#232638] bg-[#141620] overflow-x-auto flex items-center gap-1.5 no-scrollbar">
        {QUICK_STARTER_PROMPTS.map((item, i) => {
          const Icon = item.icon;
          return (
            <button
              key={i}
              onClick={() => handleSendMessage(item.prompt)}
              disabled={isLoading}
              className="flex items-center space-x-1.5 px-2.5 py-1 rounded-xl bg-[#1c2030] hover:bg-[#252a40] border border-[#2d334d] hover:border-indigo-500/40 text-[11px] text-[#cbd5e1] hover:text-white transition-all cursor-pointer flex-shrink-0 disabled:opacity-50"
            >
              <Icon className="w-3 h-3 text-indigo-400" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Input Box Area */}
      <div className="p-3 border-t border-[#232638] bg-[#151722]">
        <div className="relative flex items-center">
          <textarea
            ref={inputRef}
            rows={1}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            placeholder="Ask about this code, risks, or fix..."
            disabled={isLoading}
            className="w-full bg-[#11131c] border border-[#2b2f45] focus:border-indigo-500 rounded-xl pl-3 pr-10 py-2.5 text-xs text-white placeholder-[#64748b] focus:outline-none resize-none leading-relaxed"
          />

          <button
            onClick={() => handleSendMessage()}
            disabled={!inputText.trim() || isLoading}
            className="absolute right-2 p-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg transition-all cursor-pointer shadow-xs active:scale-95"
            title="Send Question (Enter)"
          >
            {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          </button>
        </div>

        <div className="mt-1.5 flex items-center justify-between text-[10px] text-[#64748b]">
          <span>Context auto-injected from active file</span>
          <span>Press <kbd className="px-1 py-0.5 rounded bg-[#1c2030] border border-[#2d334d] text-[9px] text-[#94a3b8]">Enter</kbd> to send</span>
        </div>
      </div>

    </div>
  );
};
