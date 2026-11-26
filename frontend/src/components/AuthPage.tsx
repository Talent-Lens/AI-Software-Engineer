import React, { useState } from 'react';
import { Terminal, ShieldCheck, Sparkles, Eye, EyeOff, Lock, Mail, User, ArrowRight, CheckCircle2 } from 'lucide-react';
import { loginUser, registerUser } from '../services/api';
import { UserPublic } from '../types';

interface AuthPageProps {
  onAuthSuccess: (user: UserPublic, token: string) => void;
}

export const AuthPage: React.FC<AuthPageProps> = ({ onAuthSuccess }) => {
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Form State
  const [loginIdentifier, setLoginIdentifier] = useState('');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');

  const calculatePasswordScore = (pass: string): number => {
    let score = 0;
    if (pass.length >= 8) score += 25;
    if (/[A-Z]/.test(pass)) score += 25;
    if (/[0-9]/.test(pass)) score += 25;
    if (/[^A-Za-z0-9]/.test(pass)) score += 25;
    return score;
  };

  const passScore = calculatePasswordScore(password);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setLoading(true);

    try {
      if (isRegisterMode) {
        if (passScore < 50) {
          throw new Error('Please choose a stronger password (minimum 8 characters with numbers and mixed case).');
        }
        const data = await registerUser(email, username, password, displayName || undefined);
        onAuthSuccess(data.user, data.access_token);
      } else {
        const data = await loginUser(loginIdentifier, password);
        onAuthSuccess(data.user, data.access_token);
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Authentication failed. Please verify credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0a0a0f] text-[#d4d4d8]">
      <style>{`
        @keyframes subtleBlob {
          0%, 100% { transform: translate(0px, 0px) scale(1); }
          50% { transform: translate(30px, -20px) scale(1.05); }
        }
        .animate-subtle-blob {
          animation: subtleBlob 8s ease-in-out infinite;
        }
      `}</style>

      {/* Left Feature Showcase (Desktop only) */}
      <div className="hidden lg:flex lg:w-3/5 relative flex-col justify-between p-12 border-r border-[#27272a] bg-[#0d0d14] overflow-hidden select-none">
        <div className="absolute -top-32 -left-32 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl animate-subtle-blob" />
        <div className="absolute -bottom-32 -right-32 w-96 h-96 bg-indigo-600/10 rounded-full blur-3xl animate-subtle-blob" />

        <div className="relative z-10 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-[#007acc]">
            <Terminal className="w-6 h-6" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">CodeGuardian</span>
        </div>

        <div className="relative z-10 space-y-6 max-w-lg">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Sparkles className="w-3.5 h-3.5" /> Multi-Agent AST RAG Architecture
          </div>
          <h1 className="text-4xl font-extrabold text-white leading-tight">
            Autonomous Code Review &amp; Security Verification
          </h1>
          <p className="text-sm text-zinc-400 leading-relaxed">
            Run multi-stage AST scans, verify line citations, conduct automated SAST audits, and generate regression tests in a unified workspace.
          </p>

          <div className="bg-[#12121c]/80 backdrop-blur-md rounded-xl p-4 border border-[#27273a] shadow-2xl font-mono text-xs space-y-2">
            <div className="flex items-center gap-2 text-zinc-500 pb-2 border-b border-zinc-800">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
              <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/80" />
              <span className="w-2.5 h-2.5 rounded-full bg-green-500/80" />
              <span className="ml-2 text-zinc-400">langgraph_execution.log</span>
            </div>
            <p className="text-blue-400">&gt; Initializing hybrid AST retrieval...</p>
            <p className="text-zinc-400">&gt; Parsing syntax trees: 100% matched</p>
            <p className="text-emerald-400">&gt; Security audit: 0 vulnerabilities found</p>
          </div>
        </div>

        <div className="relative z-10 flex items-center gap-6 text-xs text-zinc-500">
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-emerald-500" />
            <span>OWASP Grounded</span>
          </div>
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4 text-blue-500" />
            <span>Deterministic Verifiers</span>
          </div>
        </div>
      </div>

      {/* Right Auth Form */}
      <div className="flex-1 flex flex-col justify-center items-center p-6 sm:p-12 relative z-10">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-2 text-center lg:text-left">
            <h2 className="text-2xl font-bold text-white tracking-tight">
              {isRegisterMode ? 'Create Workspace Account' : 'Welcome Back'}
            </h2>
            <p className="text-xs text-zinc-400">
              {isRegisterMode
                ? 'Join your automated engineering pipeline'
                : 'Enter your credentials to access the workspace'}
            </p>
          </div>

          {errorMessage && (
            <div className="p-3 text-xs bg-red-500/10 border border-red-500/20 text-red-400 rounded-lg">
              {errorMessage}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegisterMode ? (
              <>
                <div className="space-y-1">
                  <label className="text-xs text-zinc-400">Email Address</label>
                  <div className="relative">
                    <Mail className="w-4 h-4 text-zinc-500 absolute left-3 top-3" />
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="engineer@company.com"
                      className="w-full bg-[#14141e] border border-[#27273a] rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs text-zinc-400">Username</label>
                  <div className="relative">
                    <User className="w-4 h-4 text-zinc-500 absolute left-3 top-3" />
                    <input
                      type="text"
                      required
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="dev_alex"
                      className="w-full bg-[#14141e] border border-[#27273a] rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs text-zinc-400">Display Name (Optional)</label>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Alex Chen"
                    className="w-full bg-[#14141e] border border-[#27273a] rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </>
            ) : (
              <div className="space-y-1">
                <label className="text-xs text-zinc-400">Email or Username</label>
                <div className="relative">
                  <User className="w-4 h-4 text-zinc-500 absolute left-3 top-3" />
                  <input
                    type="text"
                    required
                    value={loginIdentifier}
                    onChange={(e) => setLoginIdentifier(e.target.value)}
                    placeholder="engineer@company.com or alex"
                    className="w-full bg-[#14141e] border border-[#27273a] rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>
            )}

            <div className="space-y-1">
              <label className="text-xs text-zinc-400">Password</label>
              <div className="relative">
                <Lock className="w-4 h-4 text-zinc-500 absolute left-3 top-3" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-[#14141e] border border-[#27273a] rounded-lg pl-9 pr-10 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-2.5 text-zinc-500 hover:text-zinc-300"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>

              {isRegisterMode && password.length > 0 && (
                <div className="pt-1.5 space-y-1">
                  <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${
                        passScore < 50
                          ? 'bg-red-500'
                          : passScore < 75
                          ? 'bg-yellow-500'
                          : 'bg-emerald-500'
                      }`}
                      style={{ width: `${passScore}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-zinc-500">
                    Strength: {passScore < 50 ? 'Weak' : passScore < 75 ? 'Moderate' : 'Strong'}
                  </span>
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-2 py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
            >
              {loading ? (
                <span className="animate-pulse">Processing...</span>
              ) : (
                <>
                  <span>{isRegisterMode ? 'Complete Registration' : 'Sign In'}</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          <div className="text-center pt-2">
            <button
              type="button"
              onClick={() => {
                setIsRegisterMode(!isRegisterMode);
                setErrorMessage(null);
              }}
              className="text-xs text-zinc-400 hover:text-blue-400 transition-colors"
            >
              {isRegisterMode
                ? 'Already have an account? Sign In'
                : "Don't have an account? Sign Up"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
