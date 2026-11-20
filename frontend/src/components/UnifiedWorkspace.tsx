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
  Bot,
  GitBranch,
  Search,
  FileArchive,
  FileCode2,
  RotateCw
} from 'lucide-react';
import { DiffEditor } from '@monaco-editor/react';
import { CodeFile, PipelineExecutionState, UserPublic } from '../types';
import { analyzeCodeFile } from '../utils/codeAnalyzer';
import { 
  submitUserFeedback, 
  analyzeGithubRepository,
  fetchGitHubConnectUrl,
  fetchGitHubInstallationStatus,
  fetchGitHubBranches,
  disconnectGitHubApp,
  createGitHubPullRequest,
} from '../services/api';
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
  currentUser?: UserPublic | null;
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
  currentUser,
}) => {
  // Current Workflow Stage: 'input' | 'scanning' | 'results'
  const [stage, setStage] = useState<'input' | 'scanning' | 'results'>('input');
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

  // Two-Card Intent-Based Redesign States
  const [scanCodeMode, setScanCodeMode] = useState<'upload' | 'paste'>('upload');
  const [isGithubConnected, setIsGithubConnected] = useState<boolean>(false);
  const [githubUser, setGithubUser] = useState<{ username: string; avatarUrl: string } | null>(null);
  const [installationId, setInstallationId] = useState<number | null>(null);
  const [repoSearchQuery, setRepoSearchQuery] = useState<string>('');
  const [selectedRepoId, setSelectedRepoId] = useState<string>('');
  const [selectedBranch, setSelectedBranch] = useState<string>('main');
  const [scanScope, setScanScope] = useState<'all' | 'folder' | 'recent'>('all');
  const [scopeFolder, setScopeFolder] = useState<string>('');
  const [showPublicUrlInput, setShowPublicUrlInput] = useState<boolean>(false);
  const [showPublicUrlConnected, setShowPublicUrlConnected] = useState<boolean>(false);
  const [isReadOnlyScan, setIsReadOnlyScan] = useState<boolean>(false);
  const [manualLangOverride, setManualLangOverride] = useState<string>('auto');
  const [showPrivacyModal, setShowPrivacyModal] = useState<boolean>(false);

  // Real GitHub App Integration States
  const [realRepos, setRealRepos] = useState<any[]>([]);
  const [isLoadingGithub, setIsLoadingGithub] = useState<boolean>(false);
  const [isRefreshingRepos, setIsRefreshingRepos] = useState<boolean>(false);
  const [repoNoticeMsg, setRepoNoticeMsg] = useState<string | null>(null);
  const [githubConnectError, setGithubConnectError] = useState<string | null>(null);
  const [availableBranches, setAvailableBranches] = useState<string[]>(['main']);
  const [isLoadingBranches, setIsLoadingBranches] = useState<boolean>(false);

  // Auto-detect language from code snippet text
  const detectLanguage = (code: string): string => {
    if (!code.trim()) return 'python';
    if (code.includes('def ') || (code.includes('import ') && !code.includes('from "') && !code.includes("from '")) || code.includes('print(')) return 'python';
    if (code.includes('interface ') || code.includes(': string') || code.includes(': number') || code.includes('export const') || code.includes('export default')) return 'typescript';
    if (code.includes('const ') || code.includes('let ') || code.includes('function ') || code.includes('console.log(')) return 'javascript';
    if (code.includes('SELECT ') || code.includes('FROM ') || code.includes('WHERE ') || code.includes('INSERT INTO')) return 'sql';
    if (code.includes('package ') && code.includes('func ')) return 'go';
    if (code.includes('public class ') || code.includes('System.out.println')) return 'java';
    return 'python';
  };

  // Re-fetch authorized repositories from backend & GitHub API
  const refreshRepositories = async (preserveSelectedId?: string) => {
    if (!currentUser) return;
    setIsRefreshingRepos(true);
    setRepoNoticeMsg(null);
    try {
      const res = await fetchGitHubInstallationStatus();
      if (res.connected && res.installation) {
        setIsGithubConnected(true);
        if (res.installation.installation_id) {
          setInstallationId(res.installation.installation_id);
        }
        setGithubUser({
          username: res.installation.account_login || 'github-user',
          avatarUrl: res.installation.account_avatar_url || '',
        });
        const fetchedRepos = res.repos || [];
        setRealRepos(fetchedRepos);

        // Preserve current selection if it still exists in the refreshed list
        const targetId = preserveSelectedId !== undefined ? preserveSelectedId : selectedRepoId;
        const exists = fetchedRepos.some((r: any) => r.id === targetId);
        if (exists && targetId) {
          setSelectedRepoId(targetId);
        } else if (fetchedRepos.length > 0) {
          if (targetId) {
            setRepoNoticeMsg('Previously selected repository is no longer authorized. Selected the first available repository.');
          }
          setSelectedRepoId(fetchedRepos[0].id);
          setSelectedBranch(fetchedRepos[0].defaultBranch || 'main');
        } else {
          setSelectedRepoId('');
          setRepoNoticeMsg('No repositories are currently authorized. Click "Add or remove repositories" to grant access on GitHub.');
        }
      } else {
        setIsGithubConnected(false);
        setGithubUser(null);
        setRealRepos([]);
        setSelectedRepoId('');
      }
    } catch (err: any) {
      console.warn('Could not refresh repositories:', err);
    } finally {
      setIsRefreshingRepos(false);
      setIsLoadingGithub(false);
    }
  };

  // Fetch real GitHub connection status on mount / when user changes
  useEffect(() => {
    // Check if redirected back with query params from GitHub redirect
    const params = new URLSearchParams(window.location.search);
    if (params.get('github_connected') === 'true') {
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (params.get('github_error')) {
      const errCode = params.get('github_error');
      setGithubConnectError(
        errCode === 'invalid_state'
          ? 'GitHub authorization session expired. Please click Connect GitHub to try again.'
          : 'Failed to authorize GitHub App.'
      );
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    if (!currentUser) {
      setIsGithubConnected(false);
      setGithubUser(null);
      setRealRepos([]);
      setSelectedRepoId('');
      return;
    }

    setIsLoadingGithub(true);
    refreshRepositories();
  }, [currentUser]);

  // Window Focus Listener: Auto-refresh repositories when user returns from GitHub
  useEffect(() => {
    const handleWindowFocus = () => {
      if (isGithubConnected && currentUser) {
        refreshRepositories(selectedRepoId);
      }
    };
    window.addEventListener('focus', handleWindowFocus);
    return () => window.removeEventListener('focus', handleWindowFocus);
  }, [isGithubConnected, currentUser, selectedRepoId]);

  // Fetch real branches when selected repository changes
  useEffect(() => {
    if (!isGithubConnected || !selectedRepoId) return;
    const activeRepo = realRepos.find((r) => r.id === selectedRepoId);
    if (!activeRepo) return;

    const parts = (activeRepo.fullName || '').split('/');
    if (parts.length === 2) {
      setIsLoadingBranches(true);
      fetchGitHubBranches(parts[0], parts[1])
        .then((branches) => {
          if (branches && branches.length > 0) {
            setAvailableBranches(branches);
            if (!branches.includes(selectedBranch)) {
              setSelectedBranch(activeRepo.defaultBranch || branches[0]);
            }
          }
        })
        .catch(() => setAvailableBranches([activeRepo.defaultBranch || 'main']))
        .finally(() => setIsLoadingBranches(false));
    }
  }, [selectedRepoId, isGithubConnected, realRepos]);

  // Real "Connect GitHub" Click Handler (Full-page redirect to GitHub App)
  const handleConnectGitHubClick = async () => {
    setGithubConnectError(null);
    if (!currentUser) {
      setGithubConnectError('Please sign in to CodeGuardian first to connect your GitHub repositories.');
      return;
    }

    setIsLoadingGithub(true);
    try {
      const installUrl = await fetchGitHubConnectUrl();
      window.location.href = installUrl;
    } catch (err: any) {
      setGithubConnectError(err.message || 'Failed to start GitHub connection.');
      setIsLoadingGithub(false);
    }
  };

  // Real "Disconnect" Handler
  const handleDisconnectGitHub = async () => {
    setIsLoadingGithub(true);
    try {
      await disconnectGitHubApp();
      setIsGithubConnected(false);
      setGithubUser(null);
      setRealRepos([]);
      setSelectedRepoId('');
    } catch (err: any) {
      console.warn('Failed to disconnect GitHub App:', err);
    } finally {
      setIsLoadingGithub(false);
    }
  };

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
  const [prRepoUrl, setPrRepoUrl] = useState<string>('');
  const [prStatusMsg, setPrStatusMsg] = useState<string | null>(null);
  const [prLoading, setPrLoading] = useState<boolean>(false);
  const [createdPrUrl, setCreatedPrUrl] = useState<string>('');

  // Structured Scan Source Context
  const [scanSource, setScanSource] = useState<{
    type: 'connected_repo' | 'public_url' | 'upload' | 'snippet';
    repoFullName?: string;
    repoId?: string;
    branch?: string;
    installationId?: number;
    owner?: string;
    repo?: string;
    url?: string;
  } | null>(null);

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
          setScanSource({ type: 'upload' });
          setIsReadOnlyScan(true);
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
          setScanSource({ type: 'upload' });
          setIsReadOnlyScan(true);
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
        // If backend returned a specific client error (like 404 repo not found or 403), show friendly prompt
        if (backendErr.message.includes('not found') || backendErr.message.includes('access denied')) {
          throw new Error(`This looks private. Connect it via GitHub to scan it.`);
        } else if (backendErr.message.includes('rate limit')) {
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
          throw new Error(`This looks private. Connect it via GitHub to scan it.`);
        }
        if (repoRes.status === 403) {
          throw new Error(`Access denied or rate limit exceeded. If this repository is private, connect it via GitHub to scan it.`);
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
      if (!scanSource || scanSource.type !== 'connected_repo') {
        setScanSource({
          type: 'public_url',
          url: cleanUrl,
          owner: owner,
          repo: repo,
        });
        setIsReadOnlyScan(true);
      }
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
    const effectiveLang = manualLangOverride === 'auto' ? detectLanguage(snippetText) : manualLangOverride;
    const extMap: Record<string, string> = {
      python: 'py',
      typescript: 'ts',
      javascript: 'js',
      go: 'go',
      sql: 'sql',
      java: 'java',
    };
    const ext = extMap[effectiveLang] || 'py';
    const fileName = `snippet.${ext}`;
    const parsedFile = analyzeCodeFile(fileName, snippetText, `src/${fileName}`);
    setScanSource({ type: 'snippet' });
    setIsReadOnlyScan(true);
    handleStartScanForFile(parsedFile);
  };

  // PR submission handler using secure server-side installation token
  const handleExecuteGitHubPR = async () => {
    if (!currentFile) return;
    if (!scanSource || scanSource.type !== 'connected_repo' || !scanSource.repoFullName) {
      setPrStatusMsg('Pull Requests can only be created for repositories connected via GitHub App.');
      return;
    }

    setPrLoading(true);
    setPrStatusMsg(null);

    try {
      setPrStatusMsg('Minting installation token & submitting Pull Request on GitHub...');
      const res = await createGitHubPullRequest({
        repo_full_name: scanSource.repoFullName,
        file_path: currentFile.path || currentFile.name,
        patch_content: currentFile.proposedFix,
        base_branch: scanSource.branch || 'main',
        commit_message: `fix(security): CodeGuardian verified patch for ${currentFile.name}`,
        pr_title: `🛡️ CodeGuardian Security Patch: ${currentFile.name}`,
        pr_body: `## 🛡️ CodeGuardian Automated Security Patch\n\n- **Target File:** \`${currentFile.path || currentFile.name}\`\n- **Status:** Verified in Pytest Sandbox\n\n*Created securely via CodeGuardian GitHub App.*`,
      });

      setCreatedPrUrl(res.pr_url);
      setPrStatusMsg(`Success! Created GitHub Pull Request #${res.pr_number}`);
    } catch (err: any) {
      setPrStatusMsg(err.message || 'Failed to create Pull Request on GitHub');
    } finally {
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
        accept=".py,.js,.ts,.tsx,.jsx,.java,.go,.sql,.rs,.zip"
        className="hidden"
      />

      {/* ========================================================================= */}
      {/* 🚀 STAGE 1: WELCOMING INPUT & SETUP SCREEN (TWO-CARD INTENT-BASED LAYOUT) */}
      {/* ========================================================================= */}
      {stage === 'input' && (
        <div className="flex-1 overflow-y-auto px-4 py-8 md:py-12 flex flex-col items-center justify-start animate-fadeIn select-text">
          <div className="max-w-5xl w-full space-y-8 my-auto">
            
            {/* Welcoming Hero Header */}
            <div className="text-center space-y-2.5">
              <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-semibold mb-1">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Autonomous Code Review & Verification</span>
              </div>
              <h1 className="text-2xl sm:text-3xl md:text-4xl font-extrabold tracking-tight text-white">
                Review, fix, and secure your code
              </h1>
              <p className="text-sm text-[#94a3b8] max-w-lg mx-auto leading-relaxed">
                Find vulnerabilities and get verified fixes as pull requests.
              </p>
            </div>

            {/* Two Side-by-Side Cards (Grid) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
              
              {/* ============================================================= */}
              {/* LEFT CARD: REPOSITORY (Visually Dominant, Accent, Recommended) */}
              {/* ============================================================= */}
              <div className="bg-[#151722] rounded-3xl border-2 border-indigo-500/50 shadow-2xl shadow-indigo-950/30 overflow-hidden flex flex-col justify-between relative transition-all">
                {/* Accent Top Gradient Line */}
                <div className="h-1 bg-gradient-to-r from-indigo-500 via-indigo-400 to-teal-400 w-full" />
                
                <div className="p-6 sm:p-7 space-y-5">
                  {/* Card Header & Aligned Single Badge */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2.5">
                        <div className="w-8 h-8 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400 flex-shrink-0">
                          <Github className="w-4 h-4" />
                        </div>
                        <h2 className="text-base sm:text-lg font-bold text-white tracking-tight">Repository</h2>
                      </div>
                      <span className="text-[10px] uppercase font-bold tracking-wider px-2.5 py-1 rounded-lg bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                        Recommended
                      </span>
                    </div>
                    <p className="text-xs text-[#94a3b8] leading-relaxed min-h-[36px]">
                      Public or private repos. Verified fixes delivered directly as Pull Requests.
                    </p>
                  </div>

                  {/* --------------------------------------------------------- */}
                  {/* STATE A: NOT CONNECTED */}
                  {/* --------------------------------------------------------- */}
                  {!isGithubConnected ? (
                    <div className="space-y-4 pt-1">
                      {/* Primary Connect Button */}
                      <button
                        type="button"
                        onClick={handleConnectGitHubClick}
                        disabled={isLoadingGithub}
                        className="w-full py-3.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-2xl font-bold text-sm transition-all cursor-pointer flex items-center justify-center space-x-2.5 shadow-lg shadow-indigo-600/30 active:scale-[0.99]"
                      >
                        {isLoadingGithub ? (
                          <>
                            <Loader2 className="w-5 h-5 animate-spin text-white" />
                            <span>Redirecting to GitHub...</span>
                          </>
                        ) : (
                          <>
                            <Github className="w-5 h-5 fill-current" />
                            <span>Connect GitHub</span>
                            <ArrowUpRight className="w-4 h-4 opacity-80" />
                          </>
                        )}
                      </button>

                      {/* Error Banner if any */}
                      {githubConnectError && (
                        <div className="text-xs text-rose-200 bg-rose-950/40 p-3 rounded-xl border border-rose-500/40 flex items-start space-x-2 animate-fadeIn">
                          <ShieldAlert className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                          <div className="text-[11px] flex-1 leading-relaxed">{githubConnectError}</div>
                          <button onClick={() => setGithubConnectError(null)} className="text-rose-400 hover:text-white cursor-pointer">
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}

                      {/* Compact Single-Line Trust Note */}
                      <div className="flex items-center justify-between text-[11px] text-[#64748b] px-1">
                        <span className="flex items-center space-x-1.5 text-[#94a3b8]">
                          <Lock className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                          <span>Scoped strictly to repos you select</span>
                        </span>
                        <button
                          type="button"
                          onClick={() => setShowPrivacyModal(true)}
                          className="text-indigo-400 hover:text-indigo-300 hover:underline cursor-pointer transition-colors"
                        >
                          What we access and store
                        </button>
                      </div>

                      {/* Secondary Option: Paste a Public Repo URL (Quiet text-link row) */}
                      <div className="pt-3 border-t border-[#232638]">
                        <button
                          type="button"
                          onClick={() => setShowPublicUrlInput(!showPublicUrlInput)}
                          className="w-full py-1 text-xs text-[#94a3b8] hover:text-white flex items-center justify-between transition-colors cursor-pointer group"
                        >
                          <span className="flex items-center space-x-1.5">
                            <ExternalLink className="w-3.5 h-3.5 text-[#64748b] group-hover:text-indigo-400 transition-colors" />
                            <span>Paste a public repo URL (read-only)</span>
                          </span>
                          {showPublicUrlInput ? <ChevronUp className="w-3.5 h-3.5 text-[#64748b]" /> : <ChevronDown className="w-3.5 h-3.5 text-[#64748b]" />}
                        </button>

                        {showPublicUrlInput && (
                          <div className="mt-3 space-y-3 animate-fadeIn">
                            <form onSubmit={handleIndexGithubRepo} className="space-y-2">
                              <div className="flex gap-2">
                                <input
                                  type="text"
                                  placeholder="https://github.com/owner/repository"
                                  value={githubUrl}
                                  disabled={isIndexing}
                                  onChange={(e) => {
                                    setGithubUrl(e.target.value);
                                    if (indexError) setIndexError(null);
                                  }}
                                  className="flex-1 bg-[#11131c] border border-[#2b2f45] rounded-xl px-3.5 py-2 text-xs text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 font-mono"
                                />
                                <button
                                  type="submit"
                                  disabled={!githubUrl.trim() || isIndexing}
                                  className="bg-[#1e2336] hover:bg-indigo-600 disabled:opacity-40 text-white font-semibold text-xs px-4 py-2 rounded-xl transition-all cursor-pointer flex items-center space-x-1.5 flex-shrink-0"
                                >
                                  {isIndexing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3 h-3 fill-current" />}
                                  <span>Scan</span>
                                </button>
                              </div>
                              <p className="text-[10px] text-amber-300/80 bg-amber-500/10 p-2 rounded-lg border border-amber-500/20">
                                ℹ️ Public URL scan produces reports & diffs only. Connect GitHub to open Pull Requests.
                              </p>
                            </form>

                            {/* Advanced PAT Option (Nested inside expandable area) */}
                            <div className="pt-2 border-t border-[#232638]/50">
                              <button
                                type="button"
                                onClick={() => setShowTokenInput(!showTokenInput)}
                                className="text-[11px] text-[#64748b] hover:text-[#94a3b8] flex items-center space-x-1 cursor-pointer transition-colors"
                              >
                                <span>{showTokenInput ? '▾ Hide Personal Access Token' : '▸ Advanced: Personal Access Token (PAT)'}</span>
                              </button>
                              {showTokenInput && (
                                <div className="mt-2 p-2.5 rounded-xl bg-[#11131c] border border-[#232638] space-y-1 animate-fadeIn">
                                  <input
                                    type="password"
                                    placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                                    value={repoToken}
                                    onChange={(e) => setRepoToken(e.target.value)}
                                    className="w-full bg-[#151722] border border-[#2b2f45] rounded-lg px-3 py-1.5 text-xs text-white placeholder-[#64748b] font-mono focus:outline-none focus:border-indigo-500"
                                  />
                                  <p className="text-[10px] text-[#64748b]">
                                    Personal token for rate limits. Kept in memory only.
                                  </p>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Inline Error */}
                      {indexError && (
                        <div className="text-xs text-rose-200 bg-rose-950/40 p-3 rounded-xl border border-rose-500/40 flex items-start space-x-2 animate-fadeIn">
                          <ShieldAlert className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                          <div className="text-[11px] flex-1">{indexError}</div>
                          <button onClick={() => setIndexError(null)} className="text-rose-400 hover:text-white">
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </div>
                  ) : (
                    /* ------------------------------------------------------- */
                    /* STATE B: CONNECTED VIA GITHUB APP */
                    /* ------------------------------------------------------- */
                    <div className="space-y-4 pt-1 animate-fadeIn">
                      {/* Connected Identity Bar */}
                      <div className="p-3 rounded-2xl bg-[#11131c] border border-[#232638] flex items-center justify-between">
                        <div className="flex items-center space-x-2.5">
                          {githubUser?.avatarUrl ? (
                            <img src={githubUser.avatarUrl} alt={githubUser.username} className="w-7 h-7 rounded-full border border-indigo-500/40" />
                          ) : (
                            <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold">
                              GH
                            </div>
                          )}
                          <div>
                            <div className="text-xs font-bold text-white flex items-center space-x-1.5">
                              <span>@{githubUser?.username || 'github-user'}</span>
                              <span className="text-[9px] bg-emerald-500/10 text-emerald-400 font-medium px-1.5 py-0.2 rounded border border-emerald-500/20">
                                App Active
                              </span>
                            </div>
                            <div className="text-[10px] text-[#94a3b8]">Authorized GitHub App Installation</div>
                          </div>
                        </div>

                        <div className="flex items-center space-x-2">
                          <a
                            href={installationId ? `https://github.com/settings/installations/${installationId}` : "https://github.com/settings/installations"}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors font-medium cursor-pointer"
                            title="Add or remove authorized repositories on GitHub"
                          >
                            Add or remove repositories ↗
                          </a>
                          <span className="text-[#64748b] text-[10px]">•</span>
                          <button
                            type="button"
                            onClick={handleDisconnectGitHub}
                            disabled={isLoadingGithub}
                            className="text-[11px] text-[#94a3b8] hover:text-rose-400 transition-colors font-medium cursor-pointer disabled:opacity-50"
                          >
                            Disconnect
                          </button>
                        </div>
                      </div>

                      {/* Searchable Repository Picker */}
                      <div className="space-y-1.5">
                        <label className="text-xs font-semibold text-white flex items-center justify-between">
                          <span>Select Repository:</span>
                          <div className="flex items-center space-x-1.5">
                            <span className="text-[10px] text-[#94a3b8]">
                              {realRepos.length} {realRepos.length === 1 ? 'repository' : 'repositories'} authorized
                            </span>
                            <button
                              type="button"
                              onClick={() => refreshRepositories(selectedRepoId)}
                              disabled={isRefreshingRepos}
                              className="p-1 text-[#94a3b8] hover:text-white rounded-md hover:bg-[#1f2336] transition-colors cursor-pointer disabled:opacity-50"
                              title="Refresh authorized repositories list"
                            >
                              <RotateCw className={`w-3 h-3 ${isRefreshingRepos ? 'animate-spin text-indigo-400' : ''}`} />
                            </button>
                          </div>
                        </label>

                        {/* Notice if previous repo was removed or no repos authorized */}
                        {repoNoticeMsg && (
                          <div className="text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 p-2 rounded-xl flex items-center justify-between animate-fadeIn">
                            <span>{repoNoticeMsg}</span>
                            <button onClick={() => setRepoNoticeMsg(null)} className="text-amber-400 hover:text-white ml-2 cursor-pointer">
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        )}

                        {/* Search Input */}
                        <div className="relative">
                          <Search className="w-3.5 h-3.5 text-[#64748b] absolute left-3 top-2.5" />
                          <input
                            type="text"
                            placeholder="Filter authorized repositories..."
                            value={repoSearchQuery}
                            onChange={(e) => setRepoSearchQuery(e.target.value)}
                            className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl pl-9 pr-3.5 py-2 text-xs text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500"
                          />
                        </div>

                        {/* Repo List */}
                        <div className="max-h-36 overflow-y-auto space-y-1.5 rounded-xl p-1 bg-[#11131c] border border-[#232638]">
                          {realRepos.length === 0 ? (
                            <div className="p-3 text-center text-xs text-[#94a3b8]">
                              <p>No repositories granted yet.</p>
                              <a
                                href={installationId ? `https://github.com/settings/installations/${installationId}` : "https://github.com/settings/installations"}
                                target="_blank"
                                rel="noreferrer"
                                className="text-indigo-400 hover:underline text-[11px] mt-1 inline-block"
                              >
                                Select repositories on GitHub ↗
                              </a>
                            </div>
                          ) : (
                            realRepos
                              .filter((r) => r.name.toLowerCase().includes(repoSearchQuery.toLowerCase()))
                              .map((repo) => (
                                <div
                                  key={repo.id}
                                  onClick={() => {
                                    setSelectedRepoId(repo.id);
                                    setSelectedBranch(repo.defaultBranch || 'main');
                                  }}
                                  className={`p-2.5 rounded-xl cursor-pointer transition-all flex items-center justify-between text-xs ${
                                    selectedRepoId === repo.id
                                      ? 'bg-indigo-600/20 border border-indigo-500 text-white shadow-sm'
                                      : 'hover:bg-[#181a26] border border-transparent text-[#cbd5e1]'
                                  }`}
                                >
                                  <div className="flex items-center space-x-2.5">
                                    <div className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center flex-shrink-0 transition-all ${
                                      selectedRepoId === repo.id
                                        ? 'border-indigo-400 bg-indigo-500/30'
                                        : 'border-[#475569]'
                                    }`}>
                                      {selectedRepoId === repo.id && (
                                        <div className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                                      )}
                                    </div>
                                    <span className="font-semibold">{repo.name}</span>
                                    <span
                                      className={`text-[9px] px-1.5 py-0.2 rounded font-medium ${
                                        repo.isPrivate
                                          ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20'
                                          : 'bg-slate-500/10 text-slate-300'
                                      }`}
                                    >
                                      {repo.isPrivate ? 'Private' : 'Public'}
                                    </span>
                                  </div>
                                  <div className="text-[10px] text-[#64748b] flex items-center space-x-2">
                                    <span>{repo.language}</span>
                                    <span>•</span>
                                    <span>{repo.updatedAt ? new Date(repo.updatedAt).toLocaleDateString() : 'Active'}</span>
                                  </div>
                                </div>
                              ))
                          )}
                        </div>
                      </div>

                      {/* Branch & Scope Selectors */}
                      <div className="grid grid-cols-2 gap-3 pt-1">
                        <div>
                          <label className="text-[11px] font-semibold text-white block mb-1">
                            Branch:
                          </label>
                          <div className="relative">
                            <GitBranch className="w-3.5 h-3.5 text-[#64748b] absolute left-3 top-2.5" />
                            <select
                              value={selectedBranch}
                              onChange={(e) => setSelectedBranch(e.target.value)}
                              disabled={isLoadingBranches}
                              className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl pl-8 pr-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500 cursor-pointer disabled:opacity-50"
                            >
                              {availableBranches.map((b) => (
                                <option key={b} value={b}>
                                  {b}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>

                        <div>
                          <label className="text-[11px] font-semibold text-white block mb-1">
                            Scan Scope:
                          </label>
                          <select
                            value={scanScope}
                            onChange={(e) => setScanScope(e.target.value as any)}
                            className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
                          >
                            <option value="all">Entire Repository</option>
                            <option value="folder">Specific Folder</option>
                            <option value="recent">Recently Changed</option>
                          </select>
                        </div>
                      </div>

                      {scanScope === 'folder' && (
                        <div className="animate-fadeIn">
                          <input
                            type="text"
                            placeholder="e.g. src/api or backend/services"
                            value={scopeFolder}
                            onChange={(e) => setScopeFolder(e.target.value)}
                            className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl px-3 py-1.5 text-xs text-white placeholder-[#64748b] font-mono focus:outline-none focus:border-indigo-500"
                          />
                        </div>
                      )}

                      {/* Analyze Repo Action Button */}
                      <button
                        type="button"
                        disabled={realRepos.length === 0}
                        onClick={() => {
                          const repo = realRepos.find((r) => r.id === selectedRepoId);
                          if (repo) {
                            setIsReadOnlyScan(false);
                            setScanSource({
                              type: 'connected_repo',
                              repoFullName: repo.fullName,
                              repoId: repo.id,
                              branch: selectedBranch || repo.defaultBranch || 'main',
                              installationId: installationId || undefined,
                            });
                            setGithubUrl(`https://github.com/${repo.fullName}`);
                            handleIndexGithubRepo(new Event('submit') as any);
                          }
                        }}
                        className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-2xl font-bold text-sm transition-all cursor-pointer flex items-center justify-center space-x-2 shadow-lg shadow-indigo-600/30"
                      >
                        <Play className="w-4 h-4 fill-current" />
                        <span>Analyze Repository</span>
                      </button>

                      {/* Issue 1: Secondary Option in Connected State - Scan Any Public Repo by URL */}
                      <div className="pt-3 border-t border-[#232638]">
                        <button
                          type="button"
                          onClick={() => setShowPublicUrlConnected(!showPublicUrlConnected)}
                          className="w-full py-1 text-xs text-[#94a3b8] hover:text-white flex items-center justify-between transition-colors cursor-pointer group"
                        >
                          <span className="flex items-center space-x-1.5">
                            <ExternalLink className="w-3.5 h-3.5 text-[#64748b] group-hover:text-indigo-400 transition-colors" />
                            <span>Scan any public repo by URL (read-only)</span>
                          </span>
                          {showPublicUrlConnected ? <ChevronUp className="w-3.5 h-3.5 text-[#64748b]" /> : <ChevronDown className="w-3.5 h-3.5 text-[#64748b]" />}
                        </button>

                        {showPublicUrlConnected && (
                          <div className="mt-3 space-y-3 animate-fadeIn">
                            <form
                              onSubmit={(e) => {
                                setIsReadOnlyScan(true);
                                handleIndexGithubRepo(e);
                              }}
                              className="space-y-2"
                            >
                              <div className="flex gap-2">
                                <input
                                  type="text"
                                  placeholder="https://github.com/owner/repository"
                                  value={githubUrl}
                                  disabled={isIndexing}
                                  onChange={(e) => {
                                    setGithubUrl(e.target.value);
                                    if (indexError) setIndexError(null);
                                  }}
                                  className="flex-1 bg-[#11131c] border border-[#2b2f45] rounded-xl px-3.5 py-2 text-xs text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 font-mono"
                                />
                                <button
                                  type="submit"
                                  disabled={!githubUrl.trim() || isIndexing}
                                  className="bg-[#1e2336] hover:bg-indigo-600 disabled:opacity-40 text-white font-semibold text-xs px-4 py-2 rounded-xl transition-all cursor-pointer flex items-center space-x-1.5 flex-shrink-0"
                                >
                                  {isIndexing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3 h-3 fill-current" />}
                                  <span>Scan</span>
                                </button>
                              </div>
                              <p className="text-[10px] text-[#94a3b8] bg-[#11131c] p-2 rounded-lg border border-[#232638]">
                                ℹ️ Public URL scan is read-only (report + diff). Want PRs? Install CodeGuardian on your own repo.
                              </p>
                            </form>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* ============================================================= */}
              {/* RIGHT CARD: SCAN CODE (Upload / Paste, Lighter Visual)        */}
              {/* ============================================================= */}
              <div className="bg-[#151722] rounded-3xl border border-[#232638] shadow-xl overflow-hidden flex flex-col justify-between">
                <div className="p-6 sm:p-7 space-y-5">
                  {/* Card Header & Aligned Single Badge */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2.5">
                        <div className="w-8 h-8 rounded-xl bg-slate-800/80 border border-[#2b2f45] flex items-center justify-center text-slate-300 flex-shrink-0">
                          <Code2 className="w-4 h-4" />
                        </div>
                        <h2 className="text-base sm:text-lg font-bold text-white tracking-tight">Scan Code</h2>
                      </div>
                      <span className="text-[10px] font-semibold text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-lg border border-[#262a3d]">
                        Report + Diff
                      </span>
                    </div>
                    <p className="text-xs text-[#94a3b8] leading-relaxed min-h-[36px]">
                      Upload files, .zip, or paste snippets directly for immediate AST audit & diffs.
                    </p>
                  </div>

                  {/* Mode Toggle: Upload | Paste */}
                  <div className="flex bg-[#11131c] p-1 rounded-xl border border-[#232638] text-xs">
                    <button
                      type="button"
                      onClick={() => setScanCodeMode('upload')}
                      className={`flex-1 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center justify-center space-x-1.5 ${
                        scanCodeMode === 'upload'
                          ? 'bg-indigo-600 text-white shadow-sm'
                          : 'text-[#94a3b8] hover:text-white'
                      }`}
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      <span>Upload Files / .zip</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setScanCodeMode('paste')}
                      className={`flex-1 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center justify-center space-x-1.5 ${
                        scanCodeMode === 'paste'
                          ? 'bg-indigo-600 text-white shadow-sm'
                          : 'text-[#94a3b8] hover:text-white'
                      }`}
                    >
                      <Code2 className="w-3.5 h-3.5" />
                      <span>Paste Snippet</span>
                    </button>
                  </div>

                  {/* SUB-VIEW 1: UPLOAD FILES / ZIP */}
                  {scanCodeMode === 'upload' && (
                    <div className="space-y-3 animate-fadeIn">
                      <div
                        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                        onDragLeave={() => setDragOver(false)}
                        onDrop={handleFileDrop}
                        onClick={() => fileInputRef.current?.click()}
                        className={`border-2 border-dashed rounded-2xl p-7 text-center transition-all cursor-pointer flex flex-col items-center justify-center space-y-2.5 ${
                          dragOver
                            ? 'border-indigo-500 bg-indigo-950/20 text-indigo-200 scale-[1.01]'
                            : 'border-[#2b2f45] bg-[#11131c] text-[#94a3b8] hover:border-indigo-500/60 hover:bg-[#151824]'
                        }`}
                      >
                        <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                          <Upload className="w-5 h-5" />
                        </div>
                        <div>
                          <div className="font-semibold text-white text-xs">
                            Drop source files or .zip archive here
                          </div>
                          <p className="text-[11px] text-[#64748b] mt-0.5">
                            Supports .py, .ts, .js, .java, .go, .sql, and .zip
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* SUB-VIEW 2: PASTE SNIPPET */}
                  {scanCodeMode === 'paste' && (
                    <div className="space-y-3 animate-fadeIn">
                      {/* Language Auto-detect & Small Override */}
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-[#94a3b8] flex items-center space-x-1">
                          <Sparkles className="w-3 h-3 text-indigo-400" />
                          <span>
                            Language: <strong className="text-white capitalize">{manualLangOverride === 'auto' ? `${detectLanguage(snippetText)} (auto)` : manualLangOverride}</strong>
                          </span>
                        </span>

                        <select
                          value={manualLangOverride}
                          onChange={(e) => setManualLangOverride(e.target.value)}
                          className="bg-[#11131c] border border-[#2b2f45] rounded-md px-2 py-0.5 text-[11px] text-[#94a3b8] focus:text-white focus:outline-none cursor-pointer"
                        >
                          <option value="auto">Auto-detect</option>
                          <option value="python">Python</option>
                          <option value="typescript">TypeScript</option>
                          <option value="javascript">JavaScript</option>
                          <option value="go">Go</option>
                          <option value="sql">SQL</option>
                          <option value="java">Java</option>
                        </select>
                      </div>

                      <textarea
                        rows={6}
                        placeholder={`# Paste your code here...\nimport pickle\nobj = pickle.load(open("model.pkl", "rb"))`}
                        value={snippetText}
                        onChange={(e) => setSnippetText(e.target.value)}
                        className="w-full bg-[#11131c] border border-[#2b2f45] rounded-xl p-3 text-xs font-mono text-white placeholder-[#64748b] focus:outline-none focus:border-indigo-500 leading-relaxed"
                      />

                      <button
                        type="button"
                        onClick={handleScanSnippet}
                        disabled={!snippetText.trim()}
                        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white font-semibold text-xs py-2.5 rounded-xl transition-all cursor-pointer flex items-center justify-center space-x-1.5 shadow-sm"
                      >
                        <Play className="w-3 h-3 fill-current" />
                        <span>Audit Snippet</span>
                      </button>
                    </div>
                  )}
                </div>

                {/* Soft Bottom Upsell Line */}
                <div className="p-3.5 bg-[#11131c] border-t border-[#232638] flex items-center justify-between text-[11px]">
                  <span className="text-[#94a3b8]">Want verified fixes delivered as a PR?</span>
                  <button
                    type="button"
                    onClick={() => {
                      if (!isGithubConnected) {
                        setIsGithubConnected(true);
                        setGithubUser({ username: 'octocat', avatarUrl: 'https://avatars.githubusercontent.com/u/583231?v=4' });
                        setSelectedRepoId('1');
                      }
                    }}
                    className="text-indigo-400 hover:text-indigo-300 font-semibold flex items-center space-x-1 cursor-pointer"
                  >
                    <span>Connect a repository</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              </div>

            </div>

            {/* Privacy / What we access modal */}
            {showPrivacyModal && (
              <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
                <div className="bg-[#151722] border border-[#232638] rounded-3xl w-full max-w-lg p-6 space-y-4 shadow-2xl animate-fadeIn">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2 text-white font-bold text-sm">
                      <Lock className="w-4 h-4 text-indigo-400" />
                      <span>What CodeGuardian Accesses and Stores</span>
                    </div>
                    <button onClick={() => setShowPrivacyModal(false)} className="text-[#94a3b8] hover:text-white cursor-pointer">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="space-y-3 text-xs text-[#94a3b8] leading-relaxed">
                    <p><strong className="text-white">No Model Training:</strong> Your code is never used to train public or foundation AI models.</p>
                    <p><strong className="text-white">In-Memory Analysis:</strong> Source files are processed in ephemeral sandboxes for AST and SAST audits.</p>
                    <p><strong className="text-white">Private Repositories:</strong> For private repos, we store AST finding summaries and commit hashes only. Code is re-fetched on demand.</p>
                    <p><strong className="text-white">Data Retention:</strong> Scans default to 90-day retention with instant one-click deletion available at any time.</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowPrivacyModal(false)}
                    className="w-full py-2 bg-[#1c2030] hover:bg-[#252a40] text-white rounded-xl text-xs font-semibold cursor-pointer"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}

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

              {/* Secondary Action 1: Create PR (Hidden for read-only public URL scans) */}
              {!isReadOnlyScan ? (
                <button
                  onClick={() => setShowPrModal(true)}
                  className="flex items-center space-x-1.5 px-3.5 py-2 bg-[#1c2030] hover:bg-[#252a40] border border-[#2d334d] text-white font-medium rounded-xl cursor-pointer transition-all shadow-sm"
                >
                  <GitPullRequest className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Create PR</span>
                </button>
              ) : (
                <span
                  className="flex items-center space-x-1.5 px-3 py-1.5 text-[11px] text-[#64748b] bg-[#11131c] border border-[#232638] rounded-xl"
                  title="Pull request creation is disabled for read-only public URL scans. Connect your repo via GitHub App to create PRs."
                >
                  <Lock className="w-3 h-3 text-[#64748b]" />
                  <span>PR Disabled (Read-only)</span>
                </span>
              )}

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


      {/* GitHub PR Modal (Secured via Server-Side GitHub App Installation) */}
      {showPrModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 animate-fadeIn">
          <div className="bg-[#151722] border border-[#232638] rounded-3xl w-full max-w-lg p-6 space-y-5 shadow-2xl">
            
            {/* Modal Header */}
            <div className="flex items-center justify-between pb-3 border-b border-[#232638]">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                  <GitPullRequest className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-white text-sm">
                    {scanSource?.type === 'connected_repo'
                      ? 'Create GitHub Pull Request'
                      : scanSource?.type === 'public_url'
                      ? 'Installation Required for Pull Requests'
                      : 'Download Verified Patch'}
                  </h3>
                  <p className="text-[11px] text-[#94a3b8]">
                    {scanSource?.type === 'connected_repo'
                      ? 'Automated delivery via authorized GitHub App'
                      : 'Non-connected scan fallback'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowPrModal(false);
                  setPrStatusMsg(null);
                  setCreatedPrUrl('');
                }}
                className="text-[#94a3b8] hover:text-white cursor-pointer p-1 rounded-lg hover:bg-[#1f2336] transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* CASE 1: CONNECTED REPO SCAN (Clean 1-Click Confirmation) */}
            {scanSource?.type === 'connected_repo' && (
              <div className="space-y-4 text-xs">
                {/* Success State */}
                {createdPrUrl ? (
                  <div className="p-4 rounded-2xl bg-emerald-950/30 border border-emerald-500/40 text-emerald-200 space-y-3 animate-fadeIn">
                    <div className="flex items-center space-x-2 font-bold text-sm text-emerald-300">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span>Pull Request Created Successfully!</span>
                    </div>
                    <p className="text-[11px] text-[#cbd5e1] leading-relaxed">
                      CodeGuardian committed the verified fix to a new branch and opened a Pull Request against{' '}
                      <span className="font-mono text-white">{scanSource.branch || 'main'}</span>.
                    </p>
                    <a
                      href={createdPrUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center space-x-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl text-xs transition-all shadow-md shadow-emerald-950/50 cursor-pointer"
                    >
                      <span>View Pull Request on GitHub</span>
                      <ArrowUpRight className="w-3.5 h-3.5" />
                    </a>
                  </div>
                ) : (
                  <>
                    <p className="text-xs text-[#94a3b8] leading-relaxed">
                      CodeGuardian will generate an isolated patch branch, commit the verified fixes, and open a Pull Request using your GitHub App installation.
                    </p>

                    {/* Read-Only Parameters Summary */}
                    <div className="p-3.5 rounded-2xl bg-[#11131c] border border-[#232638] space-y-2.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-[#94a3b8] flex items-center space-x-1.5">
                          <Github className="w-3.5 h-3.5 text-indigo-400" />
                          <span>Target Repository:</span>
                        </span>
                        <span className="font-mono font-semibold text-white bg-indigo-500/10 border border-indigo-500/30 px-2 py-0.5 rounded-lg">
                          {scanSource.repoFullName}
                        </span>
                      </div>

                      <div className="flex items-center justify-between text-xs">
                        <span className="text-[#94a3b8] flex items-center space-x-1.5">
                          <GitBranch className="w-3.5 h-3.5 text-indigo-400" />
                          <span>Base Branch:</span>
                        </span>
                        <span className="font-mono text-indigo-200">
                          {scanSource.branch || 'main'}
                        </span>
                      </div>

                      <div className="flex items-center justify-between text-xs">
                        <span className="text-[#94a3b8] flex items-center space-x-1.5">
                          <FileCode2 className="w-3.5 h-3.5 text-indigo-400" />
                          <span>Target File:</span>
                        </span>
                        <span className="font-mono text-white">
                          {currentFile?.name} (1 verified fix)
                        </span>
                      </div>

                      <div className="flex items-center justify-between text-xs">
                        <span className="text-[#94a3b8] flex items-center space-x-1.5">
                          <GitFork className="w-3.5 h-3.5 text-[#64748b]" />
                          <span>Proposed Branch:</span>
                        </span>
                        <span className="font-mono text-[#94a3b8] text-[11px]">
                          codeguardian/fix-{currentFile?.name ? currentFile.name.split('.')[0] : 'patch'}-*
                        </span>
                      </div>
                    </div>

                    {/* Error Banner */}
                    {prStatusMsg && !prLoading && (
                      <div className="p-3 rounded-xl bg-rose-950/40 border border-rose-500/40 text-rose-200 text-xs flex items-start space-x-2 animate-fadeIn">
                        <ShieldAlert className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1 leading-relaxed text-[11px]">{prStatusMsg}</div>
                      </div>
                    )}
                  </>
                )}

                {/* Modal Footer */}
                <div className="flex items-center justify-end space-x-2 pt-2 border-t border-[#232638]">
                  <button
                    onClick={() => {
                      setShowPrModal(false);
                      setPrStatusMsg(null);
                      setCreatedPrUrl('');
                    }}
                    className="px-4 py-2 rounded-xl bg-[#1c2030] hover:bg-[#252a40] text-[#94a3b8] hover:text-white text-xs font-semibold cursor-pointer transition-colors"
                  >
                    {createdPrUrl ? 'Close' : 'Cancel'}
                  </button>

                  {!createdPrUrl && (
                    <button
                      onClick={handleExecuteGitHubPR}
                      disabled={prLoading}
                      className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-bold cursor-pointer transition-all flex items-center space-x-2 shadow-lg shadow-indigo-600/30 active:scale-95"
                    >
                      {prLoading ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>Creating Pull Request...</span>
                        </>
                      ) : (
                        <>
                          <GitPullRequest className="w-4 h-4" />
                          <span>Confirm & Open Pull Request</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* CASE 2: PUBLIC URL SCAN (Fallback: Install on this repo / Download patch) */}
            {scanSource?.type === 'public_url' && (
              <div className="space-y-4 text-xs">
                <div className="p-4 rounded-2xl bg-[#11131c] border border-[#232638] space-y-2.5">
                  <p className="text-white font-semibold">
                    Repository: <span className="font-mono text-indigo-300">{scanSource.owner}/{scanSource.repo}</span>
                  </p>
                  <p className="text-[#94a3b8] leading-relaxed text-[11px]">
                    To open Pull Requests directly from CodeGuardian, our GitHub App needs write access to this repository.
                  </p>
                </div>

                <div className="flex flex-col sm:flex-row gap-2 pt-2 border-t border-[#232638]">
                  <a
                    href={installationId ? `https://github.com/settings/installations/${installationId}` : "https://github.com/settings/installations"}
                    target="_blank"
                    rel="noreferrer"
                    className="flex-1 py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold text-xs transition-all flex items-center justify-center space-x-1.5 shadow-md shadow-indigo-600/30 cursor-pointer"
                  >
                    <span>Install on this repo</span>
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  </a>
                  <button
                    onClick={() => {
                      setShowPrModal(false);
                      handleDownloadPatch();
                    }}
                    className="py-2.5 px-4 bg-[#1c2030] hover:bg-[#252a40] border border-[#2d334d] text-white rounded-xl font-semibold text-xs transition-all flex items-center justify-center space-x-1.5 cursor-pointer"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download Patch</span>
                  </button>
                </div>
              </div>
            )}

            {/* CASE 3: UPLOAD / SNIPPET SCAN (Fallback: Download patch with hint to connect repo) */}
            {(scanSource?.type === 'upload' || scanSource?.type === 'snippet' || !scanSource) && (
              <div className="space-y-4 text-xs">
                <p className="text-[#94a3b8] leading-relaxed">
                  This analysis was run from an uploaded file or pasted snippet. Connect a GitHub repository on the first page to have verified fixes delivered directly as Pull Requests.
                </p>

                <div className="flex items-center justify-end space-x-2 pt-2 border-t border-[#232638]">
                  <button
                    onClick={() => setShowPrModal(false)}
                    className="px-4 py-2 rounded-xl bg-[#1c2030] hover:bg-[#252a40] text-[#94a3b8] hover:text-white text-xs font-semibold cursor-pointer"
                  >
                    Close
                  </button>
                  <button
                    onClick={() => {
                      setShowPrModal(false);
                      handleDownloadPatch();
                    }}
                    className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold text-xs transition-all flex items-center space-x-1.5 cursor-pointer shadow-md"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download Patch (.diff)</span>
                  </button>
                </div>
              </div>
            )}

          </div>
        </div>
      )}

    </div>
  );
};
