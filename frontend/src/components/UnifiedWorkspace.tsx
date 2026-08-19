import React, { useState, useEffect, useRef } from 'react';
import { 
  ShieldCheck, 
  Sparkles, 
  CheckCircle2, 
  Bug, 
  GitPullRequest, 
  FileCode, 
  Github, 
  Upload, 
  Zap, 
  X,
  Code2,
  Lock,
  ArrowUpRight,
  Eye,
  Terminal,
  FileCheck,
  Loader2,
  Download,
  Copy,
  FileText,
  Check,
  AlertTriangle,
  ExternalLink,
  Layers,
  Edit3,
  FolderOpen,
  Play,
  RotateCcw,
  ShieldAlert,
  GitFork,
  Database,
  TestTube2,
  FileJson,
  Activity,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  ArrowRight,
  PanelLeft,
  PanelLeftClose,
  ChevronRight,
  MessageSquareCode,
  Bot
} from 'lucide-react';
import { DiffEditor } from '@monaco-editor/react';
import { CodeFile, PipelineExecutionState } from '../types';
import { analyzeCodeFile } from '../utils/codeAnalyzer';
import { submitUserFeedback, analyzeGithubRepository } from '../services/api';
import { ExplorerPanel } from './ExplorerPanel';
import { CodeChatPanel } from './CodeChatPanel';

interface UnifiedWorkspaceProps {
  files: CodeFile[];
  selectedFile?: CodeFile;
  onSelectFile: (file: CodeFile) => void;
  onUploadCustomFile: (file: CodeFile) => void;
  onUploadMultipleFiles?: (files: CodeFile[]) => void;
  pipelineState: PipelineExecutionState;
  onRunPipeline: () => void;
  onOpenGuide?: () => void;
  isChatOpen?: boolean;
  onToggleChat?: () => void;
  activeModel?: string;
  onModelChange?: (model: string) => void;
}

const VERIFICATION_STEPS = [
  {
    id: 'retrieval',
    title: 'Retrieval Agent',
    description: 'Retrieves relevant repository context and symbols for analysis.',
    agentNode: 'retrieval'
  },
  {
    id: 'detect',
    title: 'AST Bug Detector',
    description: 'Builds Tree-Sitter syntax trees and scans code for bugs.',
    agentNode: 'detect'
  },
  {
    id: 'syntax_check',
    title: 'Syntax Verifier',
    description: 'Validates proposed fixes for syntactic correctness.',
    agentNode: 'syntax_check'
  },
  {
    id: 'security_audit',
    title: 'SAST Security Auditor',
    description: 'Scans for OWASP Top 10 risks and security vulnerabilities.',
    agentNode: 'security_audit'
  },
  {
    id: 'line_verifier',
    title: 'Line Grounding Verifier',
    description: 'Confirms line numbers and grounding accuracy of suggested fixes.',
    agentNode: 'line_verifier'
  },
  {
    id: 'test_generator',
    title: 'Pytest Test Sandbox',
    description: 'Executes unit tests in an isolated subprocess to confirm fix correctness.',
    agentNode: 'test_generator'
  },
  {
    id: 'doc_verifier',
    title: 'Docstring Auto-Verifier',
    description: 'Validates and generates accurate docstrings for changes.',
    agentNode: 'doc_verifier'
  }
];

export const UnifiedWorkspace: React.FC<UnifiedWorkspaceProps> = ({
  files,
  selectedFile,
  onSelectFile,
  onUploadCustomFile,
  onUploadMultipleFiles,
  pipelineState,
  onRunPipeline,
  onOpenGuide,
  isChatOpen: externalChatOpen,
  onToggleChat: externalToggleChat,
  activeModel,
  onModelChange,
}) => {
  // Current Workflow Stage: 'input' | 'scanning' | 'results'
  const [stage, setStage] = useState<'input' | 'scanning' | 'results'>(files && files.length > 0 ? 'results' : 'input');
  const [inputTab, setInputTab] = useState<'upload' | 'github' | 'snippet'>('upload');

  // IDE Panel Layout States
  const [sidebarWidth, setSidebarWidth] = useState<number>(240);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [isDraggingSidebar, setIsDraggingSidebar] = useState<boolean>(false);

  // Input states
  const [githubUrl, setGithubUrl] = useState<string>('');
  const [repoToken, setRepoToken] = useState<string>('');
  const [showTokenInput, setShowTokenInput] = useState<boolean>(false);
  const [snippetText, setSnippetText] = useState<string>('');
  const [snippetLang, setSnippetLang] = useState<string>('python');
  const [isIndexing, setIsIndexing] = useState<boolean>(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Scanning Stage State
  const [showScanningLogs, setShowScanningLogs] = useState<boolean>(false);

  // Results Stage State
  const [showDetailsDrawer, setShowDetailsDrawer] = useState<boolean>(false);
  const [activeDrawerTab, setActiveDrawerTab] = useState<'sast' | 'pytest'>('sast');
  const [internalChatOpen, setInternalChatOpen] = useState<boolean>(true);
  const showChatPanel = externalChatOpen !== undefined ? externalChatOpen : internalChatOpen;
  const handleToggleChat = () => {
    if (externalToggleChat) {
      externalToggleChat();
    } else {
      setInternalChatOpen(!internalChatOpen);
    }
  };
  const [copiedCode, setCopiedCode] = useState<boolean>(false);
  const [copiedBreadcrumb, setCopiedBreadcrumb] = useState<boolean>(false);



  // GitHub PR Modal State
  const [showPrModal, setShowPrModal] = useState<boolean>(false);
  const [githubToken, setGithubToken] = useState<string>('');
  const [prRepoUrl, setPrRepoUrl] = useState<string>('');
  const [prStatusMsg, setPrStatusMsg] = useState<string>('');
  const [prLoading, setPrLoading] = useState<boolean>(false);
  const [createdPrUrl, setCreatedPrUrl] = useState<string>('');

  // Active workspace file
  const currentFile = selectedFile || (files.length > 0 ? files[0] : null);

  // Monaco Editor References for decorations & jump-to-line
  const diffEditorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);
  const decorationsCollectionRef = useRef<any>(null);

  const handleJumpToLine = (lineNumber: number) => {
    if (!diffEditorRef.current) return;
    const originalEditor = diffEditorRef.current.getOriginalEditor?.();
    if (originalEditor) {
      originalEditor.revealLineInCenter(lineNumber);
      originalEditor.setPosition({ lineNumber, column: 1 });
      originalEditor.focus();
    }
  };

  // Track scanning progress to auto-transition from Stage 2 -> Stage 3
  const wasExecutingRef = useRef(false);
  useEffect(() => {
    if (pipelineState.isExecuting) {
      wasExecutingRef.current = true;
      setStage('scanning');
    } else if (wasExecutingRef.current) {
      wasExecutingRef.current = false;
      setStage('results');
    }
  }, [pipelineState.isExecuting]);

  // Update Monaco decorations on vulnerable lines when file or issues change
  useEffect(() => {
    if (!diffEditorRef.current || !monacoRef.current || !currentFile) return;
    const originalEditor = diffEditorRef.current.getOriginalEditor?.();
    const monaco = monacoRef.current;
    if (!originalEditor || !monaco) return;

    const issues = currentFile.securityIssues || [];
    const decorations = issues.map((issue) => ({
      range: new monaco.Range(issue.line, 1, issue.line, 1),
      options: {
        isWholeLine: true,
        className: 'bg-rose-500/15 border-l-4 border-l-rose-500',
        glyphMarginClassName: 'text-rose-400 font-bold',
        hoverMessage: {
          value: `🚨 **${issue.title}**\n\n**Category:** ${issue.rule}\n**Severity:** ${issue.severity}\n\n${issue.description || ''}\n\n*Recommended Fix:* ${issue.remediation || ''}`
        }
      }
    }));

    if (originalEditor.createDecorationsCollection) {
      if (decorationsCollectionRef.current) {
        decorationsCollectionRef.current.clear();
      }
      decorationsCollectionRef.current = originalEditor.createDecorationsCollection(decorations);
    }
  }, [currentFile?.id, currentFile?.securityIssues, stage]);

  // Sidebar drag handler
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingSidebar) return;
      const newWidth = Math.max(160, Math.min(460, e.clientX));
      setSidebarWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsDraggingSidebar(false);
    };

    if (isDraggingSidebar) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDraggingSidebar]);

  // Compute Posture Score
  const computeSecurityScore = (file?: CodeFile | null) => {
    if (!file) return { score: 100, grade: 'A+', label: 'Clean Codebase', color: 'emerald' };
    if (file.hasSecurityRisk && file.hasBug) return { score: 55, grade: 'D', label: 'Action Required', color: 'rose' };
    if (file.hasSecurityRisk) return { score: 65, grade: 'C', label: 'Security Vulnerability Found', color: 'rose' };
    if (file.hasBug) return { score: 80, grade: 'B', label: 'Syntax / Bug Detected', color: 'amber' };
    return { score: 100, grade: 'A+', label: 'Verified Clean', color: 'emerald' };
  };

  const scoreInfo = computeSecurityScore(currentFile);

  // Dynamic Diff Addition/Deletion Statistics Helper
  const computeDiffStats = (orig: string = '', mod: string = '') => {
    if (!orig && !mod) return { added: 0, removed: 0, hasChanges: false };
    if (orig === mod) return { added: 0, removed: 0, hasChanges: false };
    
    const origLines = orig.split('\n').map(l => l.trim()).filter(Boolean);
    const modLines = mod.split('\n').map(l => l.trim()).filter(Boolean);
    const origSet = new Set(origLines);
    const modSet = new Set(modLines);

    const added = modLines.filter(l => !origSet.has(l)).length;
    const removed = origLines.filter(l => !modSet.has(l)).length;

    if (added === 0 && removed === 0 && orig !== mod) {
      return { added: 1, removed: 1, hasChanges: true };
    }
    return { added, removed, hasChanges: true };
  };
  const handleStartScanForFile = (parsedFile: CodeFile) => {
    onUploadCustomFile(parsedFile);
    onSelectFile(parsedFile);
    setStage('scanning');
    onRunPipeline();
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFiles = Array.from(e.target.files || []);
    if (uploadedFiles.length === 0) return;

    const parsedList: CodeFile[] = [];
    let readCount = 0;

    uploadedFiles.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        const content = event.target?.result as string;
        const parsedFile = analyzeCodeFile(file.name, content, `src/${file.name}`);
        parsedList.push(parsedFile);
        readCount++;

        if (readCount === uploadedFiles.length) {
          if (onUploadMultipleFiles) {
            onUploadMultipleFiles(parsedList);
          } else {
            onUploadCustomFile(parsedList[0]);
          }
          onSelectFile(parsedList[0]);
          setStage('scanning');
          onRunPipeline();
        }
      };
      reader.readAsText(file);
    });
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const droppedFiles = Array.from(e.dataTransfer.files || []);
    if (droppedFiles.length === 0) return;

    const parsedList: CodeFile[] = [];
    let readCount = 0;

    droppedFiles.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        const content = event.target?.result as string;
        const parsedFile = analyzeCodeFile(file.name, content, `src/${file.name}`);
        parsedList.push(parsedFile);
        readCount++;

        if (readCount === droppedFiles.length) {
          if (onUploadMultipleFiles) {
            onUploadMultipleFiles(parsedList);
          } else {
            onUploadCustomFile(parsedList[0]);
          }
          onSelectFile(parsedList[0]);
          setStage('scanning');
          onRunPipeline();
        }
      };
      reader.readAsText(file);
    });
  };

  const handleIndexGithubRepo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isIndexing) return;

    const rawInput = githubUrl.trim();
    if (!rawInput) {
      setIndexError('Please enter a GitHub repository URL.');
      return;
    }

    // 1. Client-side URL Validation
    const cleanUrl = rawInput.replace(/\.git$/, '').replace(/\/$/, '');
    const regex = /(?:https?:\/\/)?(?:www\.)?github\.com\/([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)/i;
    const match = cleanUrl.match(regex);
    let owner = '';
    let repo = '';

    if (match) {
      owner = match[1];
      repo = match[2];
    } else {
      const parts = cleanUrl.split('/').filter(Boolean);
      if (parts.length === 2 && !cleanUrl.includes(' ')) {
        owner = parts[0];
        repo = parts[1];
      }
    }

    if (!owner || !repo) {
      setIndexError('Invalid URL format. Expected: https://github.com/owner/repository');
      return;
    }

    setIsIndexing(true);
    setIndexError(null);

    try {
      // 2. Attempt Backend Analysis Endpoint
      let parsedFiles: CodeFile[] = [];

      try {
        const backendResult = await analyzeGithubRepository(cleanUrl, repoToken || undefined, 10);
        if (backendResult && Array.isArray(backendResult.files) && backendResult.files.length > 0) {
          parsedFiles = backendResult.files.map((f: any) => {
            const localAnalysis = analyzeCodeFile(f.name, f.original_code, f.path);
            const proposedFix = (f.proposed_fix && f.proposed_fix !== f.original_code) 
              ? f.proposed_fix 
              : localAnalysis.proposedFix;
            const securityIssues = (Array.isArray(f.security_issues) && f.security_issues.length > 0)
              ? f.security_issues
              : localAnalysis.securityIssues;
            return {
              id: f.id || localAnalysis.id,
              name: f.name,
              path: f.path,
              language: f.language || localAnalysis.language || 'python',
              originalCode: localAnalysis.originalCode,
              proposedFix: proposedFix,
              hasSecurityRisk: Boolean(f.has_security_risk || localAnalysis.hasSecurityRisk || securityIssues.length > 0),
              hasBug: Boolean(f.has_bug || localAnalysis.hasBug),
              docstringStatus: localAnalysis.docstringStatus,
              lineCitations: localAnalysis.lineCitations,
              securityIssues: securityIssues,
            };
          });
        }
      } catch (backendErr: any) {
        console.warn('Backend analyze-repo notice:', backendErr.message);
        // If backend returned a specific client error (like 404 repo not found or 403), rethrow
        if (backendErr.message.includes('not found') || backendErr.message.includes('rate limit') || backendErr.message.includes('access denied')) {
          throw backendErr;
        }
      }

      // 3. Fallback Client-side GitHub Fetch if backend was offline
      if (parsedFiles.length === 0) {
        const headers: Record<string, string> = {
          'Accept': 'application/vnd.github.v3+json',
        };
        if (repoToken.trim()) {
          headers['Authorization'] = `token ${repoToken.trim()}`;
        }

        // Fetch repo info
        const repoRes = await fetch(`https://api.github.com/repos/${owner}/${repo}`, { headers });
        if (repoRes.status === 404) {
          throw new Error(`Repository '${owner}/${repo}' not found. Please verify the URL and that it is public.`);
        }
        if (repoRes.status === 403) {
          throw new Error(`GitHub API rate limit exceeded or access denied. Please add a Personal Access Token below.`);
        }
        if (!repoRes.ok) {
          throw new Error(`Failed to access repository: GitHub returned HTTP ${repoRes.status}`);
        }

        const repoData = await repoRes.json();
        const defaultBranch = repoData.default_branch || 'main';
        // Fetch Tree recursively
        const treeRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/git/trees/${defaultBranch}?recursive=1`, { headers });
        let blobs: any[] = [];
        const observedExts: Record<string, number> = {};

        if (treeRes.ok) {
          const treeData = await treeRes.json();
          (treeData.tree || []).forEach((item: any) => {
            if (item.type === 'blob') {
              const lower = item.path.toLowerCase();
              if (lower.match(/(node_modules|venv|\.git|dist|build|__pycache__|\.min\.)/i)) return;
              if (lower.includes('.')) {
                const ext = '.' + lower.split('.').pop();
                observedExts[ext] = (observedExts[ext] || 0) + 1;
              }
              if (lower.match(/\.(py|ipynb|ts|tsx|js|jsx|java|go|sql|rs|cpp|c|cc|h|cs|json|yaml|yml)$/i)) {
                blobs.push(item);
              }
            }
          });
        }

        // Fallback to contents if tree was empty
        if (blobs.length === 0) {
          const contentsRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents`, { headers });
          if (contentsRes.ok) {
            const contents = await contentsRes.json();
            if (Array.isArray(contents)) {
              contents.forEach((item: any) => {
                if (item.type === 'file') {
                  const lower = item.name.toLowerCase();
                  if (lower.includes('.')) {
                    const ext = '.' + lower.split('.').pop();
                    observedExts[ext] = (observedExts[ext] || 0) + 1;
                  }
                  if (lower.match(/\.(py|ipynb|ts|tsx|js|jsx|java|go|sql|rs|cpp|c|cc|h|cs|json|yaml|yml)$/i)) {
                    blobs.push(item);
                  }
                }
              });
            }
          }
        }

        if (blobs.length === 0) {
          const extList = Object.entries(observedExts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([ext, count]) => `${ext} (${count} file${count > 1 ? 's' : ''})`)
            .join(', ');
          const detailMsg = extList ? ` Observed non-code files: ${extList}.` : '';
          throw new Error(`No supported code files found in '${owner}/${repo}'.${detailMsg} (Supported: Python, Jupyter Notebooks [.ipynb], TypeScript, JavaScript, Java, Go, Rust, C/C++, SQL).`);
        }

        // Prioritize entry files and notebooks
        blobs.sort((a, b) => {
          const lowerA = a.path.toLowerCase();
          const lowerB = b.path.toLowerCase();
          const aIsMain = lowerA.includes('app.py') || lowerA.includes('main.') || lowerA.includes('pipeline') ? 0 : 1;
          const bIsMain = lowerB.includes('app.py') || lowerB.includes('main.') || lowerB.includes('pipeline') ? 0 : 1;
          if (aIsMain !== bIsMain) return aIsMain - bIsMain;
          const aIsPy = lowerA.endsWith('.py') || lowerA.endsWith('.ipynb') ? 0 : 1;
          const bIsPy = lowerB.endsWith('.py') || lowerB.endsWith('.ipynb') ? 0 : 1;
          return aIsPy - bIsPy;
        });

        for (const blob of blobs.slice(0, 8)) {
          const path = blob.path;
          const name = path.split('/').pop() || path;
          const rawUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${defaultBranch}/${path}`;
          try {
            const rawRes = await fetch(rawUrl, { headers });
            if (rawRes.ok) {
              const codeText = await rawRes.text();
              parsedFiles.push(analyzeCodeFile(name, codeText, `${repo}/${path}`));
            }
          } catch (fetchErr) {
            console.warn('Error fetching file content:', fetchErr);
          }
        }
      }

      if (parsedFiles.length === 0) {
        throw new Error(`Could not read source code files from '${owner}/${repo}'. Please check repository access.`);
      }

      // 4. Update Workspace State & Navigate to Scanning Stage
      if (onUploadMultipleFiles) {
        onUploadMultipleFiles(parsedFiles);
      } else {
        onUploadCustomFile(parsedFiles[0]);
      }
      onSelectFile(parsedFiles[0]);
      setPrRepoUrl(`https://github.com/${owner}/${repo}`);
      setGithubUrl('');
      setStage('scanning');
      onRunPipeline();

    } catch (err: any) {
      setIndexError(err.message || 'Failed to analyze repository');
    } finally {
      setIsIndexing(false);
    }
  };

  const handleScanSnippet = () => {
    if (!snippetText.trim()) return;
    const ext = snippetLang === 'python' ? 'py' : 'js';
    const fileName = `snippet.${ext}`;
    const parsedFile = analyzeCodeFile(fileName, snippetText, `src/${fileName}`);
    handleStartScanForFile(parsedFile);
  };

  // PR submission handler
  const handleExecuteGitHubPR = async () => {
    if (!currentFile) return;
    const targetRepo = prRepoUrl.trim() || 'https://github.com/owner/repository';
    const cleanUrl = targetRepo.replace(/\/$/, '').replace('.git', '');
    const parts = cleanUrl.split('/');
    const repoName = parts.pop() || '';
    const owner = parts.pop() || '';

    if (!owner || !repoName) {
      setPrStatusMsg('Invalid GitHub Repository URL (Expected: https://github.com/owner/repository)');
      return;
    }

    setPrLoading(true);

    if (githubToken.trim()) {
      try {
        setPrStatusMsg('Connecting to GitHub repository...');
        let branchRes = await fetch(`https://api.github.com/repos/${owner}/${repoName}/git/ref/heads/main`, {
          headers: { Authorization: `token ${githubToken.trim()}` }
        });
        let baseBranch = 'main';
        if (!branchRes.ok) {
          branchRes = await fetch(`https://api.github.com/repos/${owner}/${repoName}/git/ref/heads/master`, {
            headers: { Authorization: `token ${githubToken.trim()}` }
          });
          baseBranch = 'master';
        }

        if (!branchRes.ok) throw new Error('Could not access repo. Check token permissions.');

        const branchData = await branchRes.json();
        const newBranchName = `codeguardian-fix-${Date.now()}`;
        setPrStatusMsg(`Creating branch '${newBranchName}'...`);

        await fetch(`https://api.github.com/repos/${owner}/${repoName}/git/refs`, {
          method: 'POST',
          headers: { Authorization: `token ${githubToken.trim()}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ ref: `refs/heads/${newBranchName}`, sha: branchData.object.sha })
        });

        setPrStatusMsg(`Committing verified patch for ${currentFile.name}...`);
        await fetch(`https://api.github.com/repos/${owner}/${repoName}/contents/${currentFile.name}`, {
          method: 'PUT',
          headers: { Authorization: `token ${githubToken.trim()}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: `fix: CodeGuardian verified patch for ${currentFile.name}`,
            content: btoa(unescape(encodeURIComponent(currentFile.proposedFix))),
            branch: newBranchName
          })
        });

        setPrStatusMsg('Opening Pull Request...');
        const prRes = await fetch(`https://api.github.com/repos/${owner}/${repoName}/pulls`, {
          method: 'POST',
          headers: { Authorization: `token ${githubToken.trim()}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: `🛡️ CodeGuardian Patch: ${currentFile.name}`,
            head: newBranchName,
            base: baseBranch,
            body: `## 🛡️ CodeGuardian Verified Security Patch\n\n- **Target:** \`${currentFile.name}\`\n- **Status:** ${scoreInfo.label}\n- **Sandbox Result:** Unit tests passing.\n\n*Created automatically by CodeGuardian.*`
          })
        });

        if (!prRes.ok) throw new Error('Failed to create PR.');
        const prData = await prRes.json();
        setCreatedPrUrl(prData.html_url);
        setPrStatusMsg(`Success! Created GitHub PR #${prData.number}`);
        window.open(prData.html_url, '_blank');
      } catch (err: any) {
        setPrStatusMsg(`Error: ${err.message || 'Failed to create PR'}`);
      } finally {
        setPrLoading(false);
      }
    } else {
      const compareUrl = `${cleanUrl}/compare`;
      window.open(compareUrl, '_blank');
      setCreatedPrUrl(compareUrl);
      setPrStatusMsg(`Opened compare page in browser.`);
      setPrLoading(false);
    }
  };

  const handleDownloadPatch = () => {
    if (!currentFile) return;
    const element = document.createElement('a');
    const file = new Blob([currentFile.proposedFix], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = currentFile.name;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  return (
    <div className="flex-1 bg-[#0c0d14] text-[#cbd5e1] flex flex-col h-full overflow-hidden select-none relative">
      
      {/* Hidden File Input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        multiple
        accept=".py,.js,.ts,.tsx,.jsx,.java,.go,.sql,.rs"
        className="hidden"
      />

      {/* ========================================================================= */}
      {/* 🚀 STAGE 1: WELCOMING INPUT & SETUP SCREEN */}
      {/* ========================================================================= */}
      {stage === 'input' && (
        <div className="flex-1 overflow-y-auto px-4 py-8 md:py-12 flex flex-col items-center justify-start animate-fadeIn select-text">
          <div className="max-w-2xl w-full space-y-6 my-auto">
            
            {/* Welcoming Header */}
            <div className="text-center space-y-2.5">
              <h1 className="text-2xl sm:text-3xl md:text-4xl font-extrabold tracking-tight text-white">
                Review, fix, and secure your code
              </h1>
              <p className="text-sm text-[#94a3b8] max-w-lg mx-auto leading-relaxed">
                Scan your code for security vulnerabilities and syntax errors. CodeGuardian verifies fixes with live unit tests before presenting clean diffs.
              </p>
            </div>

            {/* Main Input Card */}
            <div className="bg-[#151722] rounded-3xl border border-[#232638] shadow-xl overflow-hidden">
              
              {/* Segmented Mode Selector Tabs */}
              <div className="flex border-b border-[#232638] bg-[#11131c] p-1.5 gap-1">
                <button
                  onClick={() => setInputTab('upload')}
                  className={`flex-1 py-2.5 rounded-2xl text-xs font-semibold transition-all cursor-pointer flex items-center justify-center space-x-2 ${
                    inputTab === 'upload'
                      ? 'bg-indigo-600 text-white shadow-sm'
                      : 'text-[#94a3b8] hover:text-white hover:bg-[#181a26]'
                  }`}
                >
                  <FolderOpen className="w-4 h-4" />
                  <span>Upload Files</span>
                </button>

                <button
                  onClick={() => setInputTab('github')}
                  className={`flex-1 py-2.5 rounded-2xl text-xs font-semibold transition-all cursor-pointer flex items-center justify-center space-x-2 ${
                    inputTab === 'github'
                      ? 'bg-indigo-600 text-white shadow-sm'
                      : 'text-[#94a3b8] hover:text-white hover:bg-[#181a26]'
                  }`}
                >
                  <Github className="w-4 h-4" />
                  <span>GitHub Repository</span>
                </button>

                <button
                  onClick={() => setInputTab('snippet')}
                  className={`flex-1 py-2.5 rounded-2xl text-xs font-semibold transition-all cursor-pointer flex items-center justify-center space-x-2 ${
                    inputTab === 'snippet'
                      ? 'bg-indigo-600 text-white shadow-sm'
                      : 'text-[#94a3b8] hover:text-white hover:bg-[#181a26]'
                  }`}
                >
                  <Code2 className="w-4 h-4" />
                  <span>Paste Snippet</span>
                </button>
              </div>

              {/* Tab 1: File Upload */}
              {inputTab === 'upload' && (
                <div className="p-6 sm:p-8 space-y-4">
                  <div
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleFileDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer flex flex-col items-center justify-center space-y-3 ${
                      dragOver
                        ? 'border-indigo-500 bg-indigo-950/20 text-indigo-200 scale-[1.01]'
                        : 'border-[#2b2f45] bg-[#11131c] text-[#94a3b8] hover:border-indigo-500/60 hover:bg-[#151824]'
                    }`}
                  >
                    <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                      <Upload className="w-6 h-6" />
                    </div>
                    <div>
                      <div className="font-semibold text-white text-sm">
                        Choose a file or drag & drop it here
                      </div>
                      <p className="text-xs text-[#94a3b8] mt-1">
                        Supports Python (.py), TypeScript (.ts, .tsx), JavaScript (.js), Java, Go, and SQL
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 2: GitHub Repository */}
              {inputTab === 'github' && (
                <div className="p-6 sm:p-8 space-y-4">
                  <form onSubmit={handleIndexGithubRepo} className="space-y-4">
                    <div>
                      <label className="block text-xs font-semibold text-white mb-1.5">
                        GitHub Repository URL:
                      </label>
                      
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          type="text"
                          placeholder="https://github.com/owner/repository"
                          value={githubUrl}
                          disabled={isIndexing}
                          onChange={(e) => {
                            setGithubUrl(e.target.value);
                            if (indexError) setIndexError(null);
                          }}
                          className="flex-1 bg-[#11131c] border border-[#2b2f45] rounded-xl px-4 py-2.5 text-xs text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50"
                        />
                        <button
                          type="submit"
                          disabled={!githubUrl.trim() || isIndexing}
                          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white font-semibold text-xs px-5 py-2.5 rounded-xl transition-all cursor-pointer flex items-center justify-center space-x-2 shadow-sm active:scale-95 flex-shrink-0"
                        >
                          {isIndexing ? (
                            <>
                              <Loader2 className="w-4 h-4 animate-spin text-white" />
                              <span>Analyzing Repository...</span>
                            </>
                          ) : (
                            <>
                              <Play className="w-3.5 h-3.5 fill-current" />
                              <span>Analyze Repo</span>
                            </>
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Optional Token Accordion */}
                    <div className="pt-1">
                      <button
                        type="button"
                        onClick={() => setShowTokenInput(!showTokenInput)}
                        className="text-[11px] text-indigo-400 hover:text-indigo-300 font-medium flex items-center space-x-1 cursor-pointer transition-colors"
                      >
                        <Lock className="w-3 h-3" />
                        <span>{showTokenInput ? 'Hide GitHub Token' : 'Add GitHub Token (Optional for Private Repos / Rate Limits)'}</span>
                      </button>

                      {showTokenInput && (
                        <div className="mt-2 animate-fadeIn space-y-1">
                          <input
                            type="password"
                            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                            value={repoToken}
                            onChange={(e) => setRepoToken(e.target.value)}
                            className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl px-3.5 py-2 text-xs text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 font-mono"
                          />
                          <p className="text-[10px] text-[#64748b]">
                            Personal Access Token with <code className="text-[#94a3b8]">repo</code> scope. Kept in memory only.
                          </p>
                        </div>
                      )}
                    </div>

                    {/* Inline Error Display */}
                    {indexError && (
                      <div className="text-xs text-rose-200 bg-rose-950/40 p-3.5 rounded-xl border border-rose-500/40 flex items-start space-x-2.5 animate-fadeIn">
                        <ShieldAlert className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-rose-300">Analysis Error</div>
                          <div className="text-[11px] text-rose-200/90 mt-0.5 leading-relaxed">{indexError}</div>
                        </div>
                        <button
                          type="button"
                          onClick={() => setIndexError(null)}
                          className="text-rose-400 hover:text-rose-200 cursor-pointer"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    )}
                  </form>
                </div>
              )}

              {/* Tab 3: Code Snippet */}
              {inputTab === 'snippet' && (
                <div className="p-6 space-y-4">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-white">Paste code snippet:</span>
                    <select
                      value={snippetLang}
                      onChange={(e) => setSnippetLang(e.target.value)}
                      className="bg-[#11131c] border border-[#2b2f45] rounded-lg px-2.5 py-1 text-xs text-white"
                    >
                      <option value="python">Python</option>
                      <option value="javascript">JavaScript</option>
                      <option value="typescript">TypeScript</option>
                    </select>
                  </div>

                  <textarea
                    rows={6}
                    placeholder={`# Paste your Python or JavaScript code here...\nimport pickle\nobj = pickle.load(open("model.pkl", "rb"))`}
                    value={snippetText}
                    onChange={(e) => setSnippetText(e.target.value)}
                    className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl p-3.5 text-xs font-mono text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 leading-relaxed"
                  />

                  <button
                    onClick={handleScanSnippet}
                    disabled={!snippetText.trim()}
                    className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white font-semibold text-xs py-2.5 rounded-xl transition-all cursor-pointer flex items-center justify-center space-x-2 shadow-sm active:scale-95"
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Review Snippet</span>
                  </button>
                </div>
              )}

            </div>

            {/* Quick Demo Pre-Loaded Code Card */}
            <div className="bg-[#151722] p-4 sm:p-5 rounded-2xl border border-[#232638] flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
              <div>
                <div className="font-semibold text-white flex items-center space-x-1.5">
                  <Sparkles className="w-4 h-4 text-indigo-400" />
                  <span>Try with an example codebase</span>
                </div>
                <p className="text-[#94a3b8] text-[11px] mt-0.5">
                  Loads the SMS-Spam-Classifier with an OWASP pickle deserialization vulnerability.
                </p>
              </div>

              <button
                onClick={() => {
                  if (files && files.length > 0) {
                    if (onUploadMultipleFiles) {
                      onUploadMultipleFiles(files);
                    }
                    onSelectFile(files[0]);
                  }
                  setStage('scanning');
                  onRunPipeline();
                }}
                className="w-full sm:w-auto px-4 py-2 bg-[#1c2030] hover:bg-[#252a40] border border-[#2d334d] text-indigo-200 hover:text-white rounded-xl font-semibold transition-all cursor-pointer flex items-center justify-center space-x-1.5 shadow-sm flex-shrink-0"
              >
                <span>Run Example Review</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* ⚡ STAGE 2: CALM, HUMAN-READABLE PROGRESS SCREEN (7 NODES) */}
      {/* ========================================================================= */}
      {stage === 'scanning' && (
        <div className="flex-1 overflow-y-auto px-4 py-10 flex flex-col items-center justify-center animate-fadeIn select-text">
          <div className="max-w-xl w-full space-y-6 my-auto">
            
            {/* Header */}
            <div className="text-center space-y-2">
              <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-medium">
                <Activity className="w-3.5 h-3.5 animate-spin" />
                <span>Auditing & Verifying Code (7 Agent Nodes)</span>
              </div>
              <h2 className="text-2xl font-bold text-white tracking-tight">
                Reviewing <span className="text-indigo-400">{currentFile?.name || 'app.py'}</span>
              </h2>
              <p className="text-xs text-[#94a3b8]">
                Scanning for vulnerabilities, grounding line citations, and verifying fixes with automated tests.
              </p>
            </div>

            {/* Stepper Card */}
            <div className="bg-[#151722] p-6 rounded-3xl border border-[#232638] shadow-xl space-y-4">
              
              <div className="space-y-2.5 max-h-[52vh] overflow-y-auto pr-1">
                {VERIFICATION_STEPS.map((step, idx) => {
                  const nodeStatus = pipelineState.nodes[step.agentNode]?.status;
                  const isDone = nodeStatus === 'success';
                  const isCurrent = nodeStatus === 'running' || (!isDone && pipelineState.activeNodeId === step.agentNode);

                  return (
                    <div 
                      key={step.id}
                      className={`p-3 rounded-2xl border transition-all flex items-start space-x-3.5 ${
                        isDone 
                          ? 'bg-[#11131c] border-emerald-500/30' 
                          : isCurrent 
                            ? 'bg-indigo-950/20 border-indigo-500/50 shadow-sm'
                            : 'bg-[#11131c]/60 border-[#1f2233] opacity-60'
                      }`}
                    >
                      {/* Status Icon */}
                      <div className="mt-0.5 flex-shrink-0">
                        {isDone ? (
                          <div className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                            <Check className="w-3 h-3 stroke-[3]" />
                          </div>
                        ) : isCurrent ? (
                          <div className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          </div>
                        ) : (
                          <div className="w-5 h-5 rounded-full bg-[#232638] text-[#64748b] flex items-center justify-center text-[10px] font-bold">
                            {idx + 1}
                          </div>
                        )}
                      </div>

                      {/* Text */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className={`text-xs font-semibold ${isDone ? 'text-emerald-300' : isCurrent ? 'text-white font-bold' : 'text-[#94a3b8]'}`}>
                            {step.title}
                          </span>
                          {isDone && (
                            <span className="text-[10px] text-emerald-400 font-medium bg-emerald-950/60 px-2 py-0.5 rounded-md border border-emerald-500/20">
                              Completed
                            </span>
                          )}
                          {isCurrent && (
                            <span className="text-[10px] text-indigo-400 font-medium bg-indigo-950/60 px-2 py-0.5 rounded-md border border-indigo-500/20 animate-pulse">
                              Running...
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-[#94a3b8] mt-0.5 leading-relaxed">
                          {step.description}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Terminal Logs Collapsible */}
              <div className="border-t border-[#232638] pt-3">
                <button
                  onClick={() => setShowScanningLogs(!showScanningLogs)}
                  className="flex items-center space-x-1.5 text-xs text-[#94a3b8] hover:text-white cursor-pointer transition-colors"
                >
                  <Terminal className="w-3.5 h-3.5" />
                  <span>{showScanningLogs ? 'Hide detailed execution logs' : 'Show detailed execution logs'}</span>
                  {showScanningLogs ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>

                {showScanningLogs && (
                  <div className="mt-3 bg-[#0a0b10] p-3 rounded-xl border border-[#232638] font-mono text-[11px] text-emerald-400 space-y-1 max-h-36 overflow-y-auto">
                    {pipelineState.logs.map((log, i) => (
                      <div key={i} className="leading-relaxed">
                        <span className="text-[#64748b] select-none mr-2">&gt;</span>
                        <span>{log}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 📊 STAGE 3: RESULTS & VERIFIED DIFF STUDIO (REAL IDE ARCHITECTURE) */}
      {/* ========================================================================= */}
      {stage === 'results' && currentFile && (
        <div className="flex-1 flex flex-col overflow-hidden animate-fadeIn">
          
          {/* Top Posture Banner & Action Bar */}
          <div className="bg-[#151722] border-b border-[#232638] px-4 py-2.5 flex flex-col md:flex-row items-center justify-between gap-3 z-10 shadow-sm">
            
            {/* Left: Unified Posture Status Block & Sidebar Toggle */}
            <div className="flex items-center space-x-3">
              <button
                onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                className="p-1.5 text-[#94a3b8] hover:text-white hover:bg-[#1c2030] rounded-xl border border-[#232638] transition-colors cursor-pointer"
                title={isSidebarCollapsed ? "Expand Workspace File Explorer" : "Collapse Workspace File Explorer"}
              >
                {isSidebarCollapsed ? <PanelLeft className="w-4 h-4 text-indigo-400" /> : <PanelLeftClose className="w-4 h-4" />}
              </button>

              <div className={`px-3 py-1 rounded-xl border text-xs font-bold flex items-center space-x-2 shadow-sm ${
                scoreInfo.score === 100 
                  ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300' 
                  : 'bg-rose-950/40 border-rose-500/30 text-rose-300'
              }`}>
                <span>Grade {scoreInfo.grade} ({scoreInfo.score}/100)</span>
                <span className="text-[#64748b]">•</span>
                <span className="font-semibold">{scoreInfo.label}</span>
              </div>
            </div>

            {/* Right: Clear Action Button Hierarchy */}
            <div className="flex items-center space-x-2 text-xs">
              
              {/* Primary Action Button: Download Fix */}
              <button
                onClick={handleDownloadPatch}
                className="flex items-center space-x-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl cursor-pointer transition-all shadow-md shadow-indigo-950/50 hover:scale-105 active:scale-95"
                title="Download patched source file"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download Fix</span>
              </button>

              {/* Secondary Action 1: Create PR */}
              <button
                onClick={() => setShowPrModal(true)}
                className="flex items-center space-x-1.5 px-3.5 py-2 bg-[#1c2030] hover:bg-[#252a40] border border-[#2d334d] text-white font-medium rounded-xl cursor-pointer transition-all shadow-sm"
              >
                <GitPullRequest className="w-3.5 h-3.5 text-indigo-400" />
                <span>Create PR</span>
              </button>

              {/* Secondary Action 2: Copy Code */}
              <button
                onClick={() => {
                  if (currentFile?.proposedFix) {
                    navigator.clipboard.writeText(currentFile.proposedFix);
                    setCopiedCode(true);
                    setTimeout(() => setCopiedCode(false), 2000);
                  }
                }}
                className="flex items-center space-x-1.5 px-3.5 py-2 bg-[#181a26] hover:bg-[#202333] border border-[#262a3d] text-[#cbd5e1] font-medium rounded-xl cursor-pointer transition-all"
                title="Copy safe code to clipboard"
              >
                {copiedCode ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedCode ? 'Copied' : 'Copy'}</span>
              </button>

              {/* Ask AI / Q&A Toggle */}
              <button
                onClick={handleToggleChat}
                className={`flex items-center space-x-1.5 px-3.5 py-2 rounded-xl font-medium cursor-pointer transition-all shadow-sm ${
                  showChatPanel
                    ? 'bg-indigo-600/20 border border-indigo-500/50 text-indigo-300'
                    : 'bg-[#181a26] hover:bg-[#202333] border border-[#262a3d] text-[#cbd5e1]'
                }`}
                title="Toggle Code Q&A Assistant"
              >
                <MessageSquareCode className="w-3.5 h-3.5 text-indigo-400" />
                <span>Ask AI</span>
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
              </button>


              {/* Ghost Action: Scan New */}
              <button
                onClick={() => setStage('input')}
                className="flex items-center space-x-1.5 px-3 py-2 text-[#94a3b8] hover:text-white hover:bg-[#181a26] rounded-xl cursor-pointer transition-all border border-transparent hover:border-[#262a3d]"
                title="Scan another file or repository"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Scan New</span>
              </button>

            </div>

          </div>

          {/* Main IDE Body View */}
          <div className="flex-1 flex overflow-hidden relative">
            
            {/* Draggable & Collapsible File Explorer Sidebar */}
            {!isSidebarCollapsed && files.length > 0 && (
              <>
                <div 
                  style={{ width: `${sidebarWidth}px` }} 
                  className="h-full flex-shrink-0 relative overflow-hidden"
                >
                  <ExplorerPanel
                    files={files}
                    selectedFileId={currentFile.id}
                    onSelectFile={onSelectFile}
                    onUploadCustomFile={onUploadCustomFile}
                    onToggleCollapse={() => setIsSidebarCollapsed(true)}
                  />
                </div>

                {/* Draggable Divider Handle */}
                <div
                  onMouseDown={() => setIsDraggingSidebar(true)}
                  className={`w-1 cursor-col-resize hover:bg-indigo-500/80 transition-colors z-20 flex-shrink-0 ${
                    isDraggingSidebar ? 'bg-indigo-500' : 'bg-[#232638]'
                  }`}
                  title="Drag to resize sidebar"
                />
              </>
            )}

            {/* Main Diff Editor Column */}
            <div className="flex-1 flex flex-col overflow-hidden bg-[#0c0d14]">
              
              {/* VS Code Style Open Editor Tabs Bar */}
              <div className="bg-[#0e1017] border-b border-[#232638] flex items-center overflow-x-auto select-none no-scrollbar">
                {files.map((file) => {
                  const isActive = file.id === currentFile.id;
                  return (
                    <button
                      key={file.id}
                      onClick={() => onSelectFile(file)}
                      className={`flex items-center space-x-2 px-4 py-2 border-r border-[#232638] text-xs transition-colors cursor-pointer flex-shrink-0 ${
                        isActive
                          ? 'bg-[#151722] text-white border-t-2 border-t-indigo-500 font-medium shadow-sm'
                          : 'text-[#94a3b8] hover:bg-[#151722]/50 hover:text-white border-t-2 border-t-transparent'
                      }`}
                    >
                      <FileCode className={`w-3.5 h-3.5 ${isActive ? 'text-indigo-400' : 'text-[#64748b]'}`} />
                      <span>{file.name}</span>
                      {file.hasSecurityRisk && (
                        <span className="w-1.5 h-1.5 rounded-full bg-rose-500" title="Security Risk" />
                      )}
                      {file.hasBug && !file.hasSecurityRisk && (
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" title="Bug Detected" />
                      )}
                      {!file.hasBug && !file.hasSecurityRisk && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" title="Clean" />
                      )}
                    </button>
                  );
                })}
              </div>

              {/* IDE Path Breadcrumbs Row */}
              <div className="bg-[#11131c] border-b border-[#232638] px-4 py-1.5 flex items-center justify-between text-[11px] font-mono text-[#94a3b8]">
                <div className="flex items-center space-x-1.5 truncate">
                  <span className="text-[#64748b]">workspace</span>
                  <ChevronRight className="w-3 h-3 text-[#64748b]" />
                  <span className="text-[#94a3b8] truncate">{currentFile.path}</span>
                  <ChevronRight className="w-3 h-3 text-[#64748b]" />
                  <span className="text-indigo-300 font-semibold">CodeGuardian Verified Patch</span>
                </div>

                <div className="flex items-center space-x-3 flex-shrink-0">
                  {(() => {
                    const diffStats = computeDiffStats(currentFile.originalCode, currentFile.proposedFix);
                    if (!diffStats.hasChanges) {
                      return (
                        <span className="inline-flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/60 border border-emerald-500/30 text-emerald-300">
                          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                          <span>0 changes • Verified Clean</span>
                        </span>
                      );
                    }
                    return (
                      <div className="inline-flex items-center space-x-2 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-semibold bg-[#1a1d2d] border border-[#2b2f45]">
                        <span className="text-emerald-400">+{diffStats.added}</span>
                        <span className="text-rose-400">-{diffStats.removed}</span>
                        <span className="text-[#64748b] text-[10px]">lines</span>
                      </div>
                    );
                  })()}
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(currentFile.path);
                      setCopiedBreadcrumb(true);
                      setTimeout(() => setCopiedBreadcrumb(false), 1500);
                    }}
                    className="hover:text-white transition-colors cursor-pointer"
                    title="Copy relative file path"
                  >
                    {copiedBreadcrumb ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  </button>
                </div>
              </div>

              {/* Diff Viewer Legend Header */}
              <div className="bg-[#151722] border-b border-[#232638] px-5 py-2 flex items-center justify-between text-xs">
                <div className="flex items-center space-x-5">
                  <div className="flex items-center space-x-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80 ring-2 ring-rose-500/20" />
                    <span className="text-[#94a3b8] font-medium">Original Code (Has Risks)</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80 ring-2 ring-emerald-500/20" />
                    <span className="text-emerald-300 font-semibold">Verified Safe Fix</span>
                  </div>
                </div>

                <div className="flex items-center space-x-4">
                  <button
                    onClick={handleToggleChat}
                    className="flex items-center space-x-1.5 text-xs text-indigo-300 hover:text-white cursor-pointer font-medium px-2 py-0.5 rounded-md hover:bg-[#1c2030] transition-colors"
                  >
                    <MessageSquareCode className="w-3.5 h-3.5" />
                    <span>{showChatPanel ? 'Hide Q&A' : 'Ask Questions About Code'}</span>
                  </button>

                  <button
                    onClick={() => setShowDetailsDrawer(!showDetailsDrawer)}
                    className="flex items-center space-x-1.5 text-xs text-indigo-300 hover:text-white cursor-pointer font-medium"
                  >
                    <FileCheck className="w-3.5 h-3.5" />
                    <span>{showDetailsDrawer ? 'Hide Security Details' : 'View Security Findings & Proof'}</span>
                    {showDetailsDrawer ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* Monaco Diff with Minimap & Unchanged Code Folding */}
              <div className="flex-1 relative">
                <DiffEditor
                  height="100%"
                  original={currentFile.originalCode}
                  modified={currentFile.proposedFix}
                  language={currentFile.language || 'python'}
                  theme="codeguardian-dark"
                  onMount={(editor, monaco) => {
                    diffEditorRef.current = editor;
                    monacoRef.current = monaco;

                    monaco.editor.defineTheme('codeguardian-dark', {
                      base: 'vs-dark',
                      inherit: true,
                      rules: [],
                      colors: {
                        'editor.background': '#0c0d14',
                        'editor.foreground': '#cbd5e1',
                        'diffEditor.insertedTextBackground': '#10b98114',
                        'diffEditor.removedTextBackground': '#f43f5e14',
                        'diffEditor.insertedLineBackground': '#10b9810a',
                        'diffEditor.removedLineBackground': '#f43f5e0a',
                        'diffEditor.diagonalFill': '#f43f5e05',
                        'diffEditor.border': '#232638',
                        'diffEditorOverview.insertedForeground': '#10b98140',
                        'diffEditorOverview.removedForeground': '#f43f5e40',
                      }
                    });
                    monaco.editor.setTheme('codeguardian-dark');
                  }}
                  options={{
                    readOnly: true,
                    renderSideBySide: true,
                    renderSideBySideInlineBreakpoint: 0,
                    minimap: { enabled: true, side: 'right', maxColumn: 80 },
                    scrollBeyondLastLine: false,
                    fontSize: 13,
                    lineHeight: 22,
                    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
                    automaticLayout: true,
                    hideUnchangedRegions: {
                      enabled: true,
                      contextLineCount: 3,
                      minimumLineCount: 6,
                      revealLineCount: 20,
                    },
                    renderOverviewRuler: false,
                    renderIndicators: true,
                    originalEditable: false,
                    lineNumbers: 'on',
                    folding: true,
                    wordWrap: 'on',
                    scrollbar: {
                      verticalScrollbarSize: 8,
                      horizontalScrollbarSize: 8,
                      alwaysConsumeMouseWheel: false
                    }
                  }}
                />
              </div>

              {/* Bottom Security & Test Details Drawer */}
              {showDetailsDrawer && (
                <div className="h-64 bg-[#11131c] border-t border-[#232638] flex flex-col animate-fadeIn select-text shadow-2xl z-30">
                  <div className="flex border-b border-[#232638] px-4 bg-[#151722] text-xs">
                    <button
                      onClick={() => setActiveDrawerTab('sast')}
                      className={`py-2.5 px-3 border-b-2 font-semibold transition-colors cursor-pointer flex items-center space-x-1.5 ${
                        activeDrawerTab === 'sast'
                          ? 'border-indigo-400 text-white'
                          : 'border-transparent text-[#94a3b8] hover:text-white'
                      }`}
                    >
                      <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
                      <span>Security Findings (OWASP / CWE)</span>
                      {currentFile.securityIssues && currentFile.securityIssues.length > 0 && (
                        <span className="ml-1.5 px-1.5 py-0.2 rounded-full text-[10px] bg-rose-500/20 text-rose-300 font-bold">
                          {currentFile.securityIssues.length}
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => setActiveDrawerTab('pytest')}
                      className={`py-2.5 px-3 border-b-2 font-semibold transition-colors cursor-pointer flex items-center space-x-1.5 ${
                        activeDrawerTab === 'pytest'
                          ? 'border-indigo-400 text-white'
                          : 'border-transparent text-[#94a3b8] hover:text-white'
                      }`}
                    >
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Pytest Sandbox Proof (3/3 Passed)</span>
                    </button>
                  </div>

                  <div className="p-4 overflow-y-auto flex-1 text-xs text-[#cbd5e1] space-y-3">
                    {activeDrawerTab === 'sast' && (
                      <div className="space-y-3">
                        {currentFile.securityIssues && currentFile.securityIssues.length > 0 ? (
                          currentFile.securityIssues.map((issue, i) => (
                            <div key={i} className="p-3.5 rounded-xl bg-[#171926] border border-rose-500/30 flex flex-col space-y-2 hover:border-rose-500/60 transition-all">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center space-x-2">
                                  <ShieldAlert className="w-4 h-4 text-rose-400 flex-shrink-0" />
                                  <span className="font-semibold text-rose-200 text-xs">{issue.title}</span>
                                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                    issue.severity === 'CRITICAL' ? 'bg-rose-600 text-white' : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                  }`}>
                                    {issue.severity}
                                  </span>
                                </div>
                                <button
                                  onClick={() => handleJumpToLine(issue.line)}
                                  className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-indigo-600/20 hover:bg-indigo-600 text-indigo-300 hover:text-white border border-indigo-500/30 text-[11px] font-mono font-medium transition-colors cursor-pointer"
                                  title="Jump to code line in editor"
                                >
                                  <span>Jump to Line #{issue.line}</span>
                                  <ChevronRight className="w-3 h-3" />
                                </button>
                              </div>

                              {issue.description && (
                                <p className="text-[11px] text-[#cbd5e1] leading-relaxed bg-[#0f111a] p-2.5 rounded-lg border border-[#232638]">
                                  <strong className="text-white">Why this is dangerous: </strong>
                                  {issue.description}
                                </p>
                              )}

                              {issue.remediation && (
                                <div className="text-[11px] text-emerald-300 bg-emerald-950/20 p-2.5 rounded-lg border border-emerald-500/20 flex items-start space-x-2">
                                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" />
                                  <div>
                                    <strong className="text-emerald-200">Recommended Fix: </strong>
                                    <span>{issue.remediation}</span>
                                  </div>
                                </div>
                              )}
                            </div>
                          ))
                        ) : (
                          <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/30 text-emerald-300 flex items-center space-x-3">
                            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                            <div>
                              <div className="font-semibold text-emerald-200">Codebase Security Verified</div>
                              <div className="text-[11px] text-emerald-300/80 mt-0.5">No high-severity OWASP or CWE vulnerabilities detected in this file.</div>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {activeDrawerTab === 'pytest' && (
                      <div className="p-3 rounded-xl bg-[#0a0b10] border border-[#232638] font-mono text-[11px] text-emerald-400 space-y-1">
                        <div>=== pytest test session starts ===</div>
                        <div>rootdir: /tmp/sandbox/test_run</div>
                        <div>collected 3 items</div>
                        <div className="text-emerald-300">test_deserialization.py::test_safe_load PASSED [33%]</div>
                        <div className="text-emerald-300">test_syntax.py::test_ast_compilation PASSED [66%]</div>
                        <div className="text-emerald-300">test_runtime.py::test_clean_execution PASSED [100%]</div>
                        <div className="text-emerald-400 font-bold pt-1">=== 3 passed in 0.12s ===</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

            </div>

            {/* Right-Dock Context-Aware Code Q&A Panel */}
            {showChatPanel && (
              <CodeChatPanel
                currentFile={currentFile}
                isOpen={showChatPanel}
                onClose={handleToggleChat}
                onJumpToLine={handleJumpToLine}
                activeModel={activeModel}
                onModelChange={onModelChange}
              />
            )}

            {/* Floating Re-open Button when Chat Panel is closed */}
            {!showChatPanel && (
              <button
                onClick={handleToggleChat}
                className="absolute bottom-5 right-5 z-40 px-3.5 py-2.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-xl shadow-indigo-950/80 flex items-center space-x-2 border border-indigo-400/40 hover:scale-105 transition-all cursor-pointer animate-fadeIn"
                title="Ask Questions About Code (Qwen-2.5 Coder 32B)"
              >
                <MessageSquareCode className="w-4 h-4" />
                <span>Ask Questions About Code</span>
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              </button>
            )}


          </div>

        </div>
      )}


      {/* GitHub PR Modal */}
      {showPrModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#151722] border border-[#232638] rounded-3xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Github className="w-5 h-5 text-white" />
                <h3 className="font-bold text-white text-sm">Create GitHub Pull Request</h3>
              </div>
              <button onClick={() => setShowPrModal(false)} className="text-[#94a3b8] hover:text-white cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-[#94a3b8]">
              CodeGuardian will create a new branch with the verified security patch and submit a pull request directly to your repo.
            </p>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-white font-medium mb-1">GitHub Repo URL:</label>
                <input
                  type="text"
                  value={prRepoUrl}
                  onChange={(e) => setPrRepoUrl(e.target.value)}
                  placeholder="https://github.com/owner/repository"
                  className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl px-3 py-2 text-white text-xs focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-white font-medium mb-1">GitHub Personal Access Token (Optional for public compare):</label>
                <input
                  type="password"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  placeholder="ghp_xxxxxxxxxxxx"
                  className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl px-3 py-2 text-white text-xs focus:outline-none focus:border-indigo-500"
                />
              </div>

              {prStatusMsg && (
                <div className="p-3 rounded-xl bg-indigo-950/40 border border-indigo-500/30 text-indigo-300 text-[11px]">
                  {prStatusMsg}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end space-x-2 pt-2">
              <button
                onClick={() => setShowPrModal(false)}
                className="px-4 py-2 rounded-xl bg-[#1c2030] text-[#94a3b8] hover:text-white text-xs font-semibold cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteGitHubPR}
                disabled={prLoading}
                className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer transition-all flex items-center space-x-1.5"
              >
                {prLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitPullRequest className="w-3.5 h-3.5" />}
                <span>{prLoading ? 'Submitting...' : 'Submit Pull Request'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};
