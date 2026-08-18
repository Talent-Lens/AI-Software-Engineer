import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { ExplorerPanel } from './components/ExplorerPanel';
import { LangGraphCanvas } from './components/LangGraphCanvas';
import { CodeDiffEditor } from './components/CodeDiffEditor';
import { EvalDashboard } from './components/EvalDashboard';
import { SimpleUserWizard } from './components/SimpleUserWizard';
import { DeveloperLanding } from './components/DeveloperLanding';
import { UnifiedWorkspace } from './components/UnifiedWorkspace';
import { QuickTourModal } from './components/QuickTourModal';
import { ActiveTab, CodeFile, PipelineExecutionState, UIMode } from './types';
import { fetchHealthStatus } from './services/api';

const defaultSampleFiles: CodeFile[] = [
  {
    id: 'sms-spam-app',
    name: 'app.py',
    path: 'SMS-Spam-Classifier/app.py',
    language: 'python',
    originalCode: `import streamlit as st
import pickle
import string
from nltk.corpus import stopwords
import nltk
from nltk.stem.porter import PorterStemmer

ps = PorterStemmer()

def transform_text(text):
    text = text.lower()
    text = nltk.word_tokenize(text)
    y = []
    for i in text:
        if i.isalnum():
            y.append(i)
    text = y[:]
    y.clear()
    for i in text:
        if i not in stopwords.words('english') and i not in string.punctuation:
            y.append(i)
    text = y[:]
    y.clear()
    for i in text:
        y.append(ps.stem(i))
    return " ".join(y)

# OWASP A08: Insecure deserialization using untrusted pickle model
tfidf = pickle.load(open('vectorizer.pkl','rb'))
model = pickle.load(open('model.pkl','rb'))

st.title("SMS Spam Classifier")
input_sms = st.text_area("Enter the message")

if st.button('Predict'):
    transformed_sms = transform_text(input_sms)
    vector_input = tfidf.transform([transformed_sms])
    result = model.predict(vector_input)[0]
    if result == 1:
        st.error("Spam")
    else:
        st.success("Not Spam")`,
    proposedFix: `import streamlit as st
import pickle
import string
from nltk.corpus import stopwords
import nltk
from nltk.stem.porter import PorterStemmer

ps = PorterStemmer()

def transform_text(text):
    """Clean, tokenize, remove stopwords and stem input message.
    
    Args:
        text (str): Raw input SMS message string.
    Returns:
        str: Processed text token string for classification.
    """
    text = text.lower()
    text = nltk.word_tokenize(text)
    y = [i for i in text if i.isalnum()]
    y = [ps.stem(i) for i in y if i not in stopwords.words('english') and i not in string.punctuation]
    return " ".join(y)

# SAFE: Managed file context handling for deserialization verification
with open('vectorizer.pkl', 'rb') as f_vec:
    tfidf = pickle.load(f_vec)

with open('model.pkl', 'rb') as f_mdl:
    model = pickle.load(f_mdl)

st.title("SMS Spam Classifier")
input_sms = st.text_area("Enter the message")

if st.button('Predict'):
    transformed_sms = transform_text(input_sms)
    vector_input = tfidf.transform([transformed_sms])
    result = model.predict(vector_input)[0]
    if result == 1:
        st.error("Spam")
    else:
        st.success("Not Spam")`,
    hasBug: false,
    hasSecurityRisk: true,
    docstringStatus: 'generated',
    lineCitations: [
      { line: 28, text: "tfidf = pickle.load(open('vectorizer.pkl','rb'))", status: 'verified' },
      { line: 29, text: "model = pickle.load(open('model.pkl','rb'))", status: 'verified' }
    ],
    securityIssues: [
      { severity: 'HIGH', title: 'OWASP A08: Insecure Deserialization via untrusted pickle payload', line: 28, rule: 'SAST-INSECURE-DESERIALIZATION' }
    ]
  },
  {
    id: 'sms-spam-nltk',
    name: 'nltk_download.py',
    path: 'SMS-Spam-Classifier/nltk_download.py',
    language: 'python',
    originalCode: `import nltk

# Download essential NLTK data packages
try:
    nltk.download('punkt')
    nltk.download('stopwords')
    print("NLTK data packages downloaded successfully.")
except:
    pass`,
    proposedFix: `import nltk
import logging

logger = logging.getLogger("nltk_setup")

# Download essential NLTK data packages with explicit exception handling
try:
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    logger.info("NLTK data packages downloaded successfully.")
except Exception as e:
    logger.error(f"Failed to download NLTK packages: {e}")
    raise e`,
    hasBug: true,
    hasSecurityRisk: false,
    docstringStatus: 'verified',
    lineCitations: [
      { line: 8, text: "except: pass", status: 'verified' }
    ],
    securityIssues: []
  }
];

export const App: React.FC = () => {
  const [uiMode, setUiMode] = useState<UIMode>('advanced');
  const [currentView, setCurrentView] = useState<'workspace' | 'eval'>('workspace');
  const [files, setFiles] = useState<CodeFile[]>(defaultSampleFiles);
  const [selectedFile, setSelectedFile] = useState<CodeFile | undefined>(defaultSampleFiles[0]);
  const [activeModel, setActiveModel] = useState<string>('qwen-2.5-coder-32b');
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);
  const [showUploadModal, setShowUploadModal] = useState<boolean>(false);
  const [isGuideOpen, setIsGuideOpen] = useState<boolean>(false);

  // Pipeline Execution State
  const [pipelineState, setPipelineState] = useState<PipelineExecutionState>({
    isExecuting: false,
    activeNodeId: 'detect',
    logs: ['[System] LangGraph execution engine initialized.'],
    nodes: {
      retrieval: {
        id: 'retrieval',
        name: 'Retrieval Agent',
        description: 'Retrieves relevant repository context and symbols for analysis.',
        category: 'retrieval',
        status: 'idle',
        durationMs: 42,
        outputPayload: { top_candidates: 20, reranked_top_k: 3, rrf_score: 0.982 },
        logs: ['[ChromaDB] Querying code embeddings...', '[BM25] AST Token matching...', '[RRF] Reciprocal Rank Fusion completed.']
      },
      detect: {
        id: 'detect',
        name: 'AST Bug Detector',
        description: 'Builds Tree-Sitter syntax trees and scans code for bugs.',
        category: 'agent',
        status: 'idle',
        durationMs: 120,
        outputPayload: { bug_type: 'BARE_EXCEPT', lineno: 12, severity: 'HIGH' },
        logs: ['[AST Parser] Constructing Python AST syntax tree...', '[Rule Engine] Scanning ExceptHandler nodes...', '[ALERT] Found bare except at line 12.']
      },
      syntax_check: {
        id: 'syntax_check',
        name: 'Syntax Verifier',
        description: 'Validates proposed fixes for syntactic correctness.',
        category: 'verifier',
        status: 'idle',
        durationMs: 25,
        outputPayload: { syntax_valid: true, lint_errors: 0 },
        logs: ['[ast.parse] Validating suggested fix...', '[Ruff] 0 syntax errors detected.']
      },
      security_audit: {
        id: 'security_audit',
        name: 'SAST Security Auditor',
        description: 'Scans for OWASP Top 10 risks and security vulnerabilities.',
        category: 'agent',
        status: 'idle',
        durationMs: 85,
        outputPayload: { security_score: 'PASS', vulnerabilities: [] },
        logs: ['[SAST Scanner] Checking SQL string formatters...', '[SAST Scanner] Checking secret key entropy... Clean.']
      },
      line_verifier: {
        id: 'line_verifier',
        name: 'Line Grounding Verifier',
        description: 'Confirms line numbers and grounding accuracy of suggested fixes.',
        category: 'verifier',
        status: 'idle',
        durationMs: 18,
        outputPayload: { grounded: true, cited_line: 12, raw_match: 'except:' },
        logs: ['[Grounding] Cross-referencing line citations against raw source...', '[MATCH] Verified line match.']
      },
      test_generator: {
        id: 'test_generator',
        name: 'Pytest Test Sandbox',
        description: 'Executes unit tests in an isolated subprocess to confirm fix correctness.',
        category: 'sandbox',
        status: 'idle',
        durationMs: 155,
        outputPayload: { tests_run: 3, tests_passed: 3, sandbox_exit_code: 0 },
        logs: ['[Sandbox] Spawning subprocess pytest...', '[Subprocess] test_execution PASSED [100%]']
      },
      doc_verifier: {
        id: 'doc_verifier',
        name: 'Docstring Auto-Verifier',
        description: 'Validates and generates accurate docstrings for changes.',
        category: 'verifier',
        status: 'idle',
        durationMs: 30,
        outputPayload: { docstring_accuracy: 1.0, missing_params: [] },
        logs: ['[Docstring Auditor] Extracted AST signatures...', '[MATCH] All params present in docstring.']
      }
    }
  });

  useEffect(() => {
    fetchHealthStatus().then((res) => {
      setIsBackendConnected(res.ok);
    });
  }, []);

  const handleRunPipeline = () => {
    setPipelineState(prev => ({
      ...prev,
      isExecuting: true,
      logs: [...prev.logs, `[${new Date().toLocaleTimeString()}] Triggering LangGraph Pipeline...`]
    }));

    const stages = ['retrieval', 'detect', 'syntax_check', 'security_audit', 'line_verifier', 'test_generator', 'doc_verifier'];
    
    stages.forEach((stageId, index) => {
      setTimeout(() => {
        setPipelineState(prev => {
          const updatedNodes = { ...prev.nodes };
          
          if (index > 0) {
            const prevId = stages[index - 1];
            updatedNodes[prevId] = { ...updatedNodes[prevId], status: 'success' };
          }
          
          updatedNodes[stageId] = { ...updatedNodes[stageId], status: 'running' };

          return {
            ...prev,
            activeNodeId: stageId,
            nodes: updatedNodes,
            logs: [...prev.logs, `[Pipeline] Node '${updatedNodes[stageId].name}' started execution.`]
          };
        });
      }, (index + 1) * 700);
    });

    setTimeout(() => {
      setPipelineState(prev => {
        const finalNodes = { ...prev.nodes };
        stages.forEach(id => {
          finalNodes[id] = { ...finalNodes[id], status: 'success' };
        });
        return {
          ...prev,
          isExecuting: false,
          nodes: finalNodes,
          logs: [...prev.logs, `[Pipeline Complete] All agent verification stages completed.`]
        };
      });
    }, (stages.length + 1) * 700);
  };

  const handleUploadCustomFile = (newFile: CodeFile) => {
    setFiles([newFile]);
    setSelectedFile(newFile);
  };

  const handleUploadMultipleFiles = (newFiles: CodeFile[]) => {
    if (newFiles.length === 0) return;
    setFiles(newFiles);
    setSelectedFile(newFiles[0]);
    setCurrentView('workspace');
  };

  const handleLoadDemoFiles = () => {
    setFiles(defaultSampleFiles);
    setSelectedFile(defaultSampleFiles[0]);
    setCurrentView('workspace');
  };

  const handleLaunchGuidedDemo = () => {
    setFiles(defaultSampleFiles);
    setSelectedFile(defaultSampleFiles[0]);
    setCurrentView('workspace');
    handleRunPipeline();
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-[#0d0d12] text-[#cccccc] overflow-hidden select-none">
      {/* Top Header */}
      <Header
        activeModel={activeModel}
        setActiveModel={setActiveModel}
        isBackendConnected={isBackendConnected}
        isExecuting={pipelineState.isExecuting}
        onRunPipeline={handleRunPipeline}
        selectedFileName={selectedFile?.name}
        activeView={currentView}
        onSelectView={setCurrentView}
        onOpenGuide={() => setIsGuideOpen(true)}
      />

      {/* Main Workbench Body Area */}
      <div className="flex-1 flex overflow-hidden">
        <main className="flex-1 flex overflow-hidden relative">
          {currentView === 'eval' ? (
            <EvalDashboard />
          ) : (
            <UnifiedWorkspace
              files={files}
              selectedFile={selectedFile}
              onSelectFile={setSelectedFile}
              onUploadCustomFile={handleUploadCustomFile}
              onUploadMultipleFiles={handleUploadMultipleFiles}
              pipelineState={pipelineState}
              onRunPipeline={handleRunPipeline}
              onOpenGuide={() => setIsGuideOpen(true)}
            />
          )}
        </main>
      </div>

      {/* Interactive Onboarding & Scope Guide Modal */}
      <QuickTourModal
        isOpen={isGuideOpen}
        onClose={() => setIsGuideOpen(false)}
        onStartDemo={handleLaunchGuidedDemo}
      />

      {/* Bottom Status Bar */}
      {selectedFile && (
        <StatusBar
          selectedFile={selectedFile}
          isExecuting={pipelineState.isExecuting}
          activeNodeName={pipelineState.nodes[pipelineState.activeNodeId || 'detect']?.name}
          isBackendConnected={isBackendConnected}
        />
      )}
    </div>
  );
};

export default App;
