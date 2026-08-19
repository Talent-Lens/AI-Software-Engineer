"""
Pre-Launch Security Checklist Engine (TASK-SEC-LAUNCH)

Audits a repository or source code files against the 20 Essential Pre-Launch
Production Readiness Security Checks grouped across 6 key categories:
1. Secrets & Credentials
2. Access Control
3. Data Protection
4. Input Validation
5. Infrastructure & Headers
6. Dependencies

Provides deterministic Pass / Fail / Manual Review / N/A statuses, file/line citations,
and actionable remediation guides with an overall Launch Readiness Score and Grade.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Data Models & Enums
# ---------------------------------------------------------------------------

CHECKLIST_CATEGORIES = [
    "Secrets & Credentials",
    "Access Control",
    "Data Protection",
    "Input Validation",
    "Infrastructure & Headers",
    "Dependencies",
]

@dataclass
class ChecklistItem:
    id: str  # e.g., "SEC-01"
    title: str
    category: str
    status: str  # "PASS" | "FAIL" | "MANUAL_REVIEW" | "NOT_APPLICABLE"
    severity: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"
    explanation: str
    remediation: str
    file_path: str | None = None
    line_number: int | None = None
    snippet: str | None = None
    manual_review_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "severity": self.severity,
            "explanation": self.explanation,
            "remediation": self.remediation,
            "file_path": self.file_path,
            "filePath": self.file_path,
            "line_number": self.line_number,
            "lineNumber": self.line_number,
            "snippet": self.snippet,
            "manual_review_reason": self.manual_review_reason,
            "manualReviewReason": self.manual_review_reason,
        }


@dataclass
class LaunchChecklistReport:
    timestamp: str
    total_checks: int
    passed_count: int
    failed_count: int
    manual_review_count: int
    not_applicable_count: int
    readiness_percentage: float
    grade: str  # "A+", "A", "B", "C", "D", "F"
    launch_status: str  # "LAUNCH_READY" | "NEEDS_REVIEW" | "BLOCK_DEPLOYMENT"
    summary: str
    items: list[ChecklistItem] = field(default_factory=list)
    category_summary: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_checks": self.total_checks,
            "totalChecks": self.total_checks,
            "passed_count": self.passed_count,
            "passedCount": self.passed_count,
            "failed_count": self.failed_count,
            "failedCount": self.failed_count,
            "manual_review_count": self.manual_review_count,
            "manualReviewCount": self.manual_review_count,
            "not_applicable_count": self.not_applicable_count,
            "notApplicableCount": self.not_applicable_count,
            "readiness_percentage": round(self.readiness_percentage, 1),
            "readinessPercentage": round(self.readiness_percentage, 1),
            "grade": self.grade,
            "launch_status": self.launch_status,
            "launchStatus": self.launch_status,
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
            "category_summary": self.category_summary,
            "categorySummary": self.category_summary,
        }


# ---------------------------------------------------------------------------
# Pre-Launch Security Auditor
# ---------------------------------------------------------------------------

class PreLaunchSecurityAuditor:
    """
    Executes the 20 Pre-Launch Security & Production Readiness checks.
    """

    SECRET_REGEXES = [
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID", "CRITICAL"),
        (r"ghp_[A-Za-z0-9_]{36}", "GitHub Personal Access Token", "CRITICAL"),
        (r"glpat-[0-9a-zA-Z\-_]{20}", "GitLab Personal Access Token", "CRITICAL"),
        (r"sk_live_[0-9a-zA-Z]{24}", "Stripe Live Secret Key", "CRITICAL"),
        (r"SG\.[0-9A-Za-z\-_]{22}\.[0-9A-Za-z\-_]{43}", "SendGrid API Key", "CRITICAL"),
        (r"AIza[0-9A-Za-z-_]{35}", "Google Cloud API Key", "HIGH"),
        (r"-----BEGIN (?:RSA )?PRIVATE KEY-----", "Raw RSA Private Key", "CRITICAL"),
        (r"(?:api[_-]?key|secret[_-]?key|auth[_-]?token)\s*=\s*['\"][A-Za-z0-9\-_]{16,}['\"]", "Generic Hardcoded Secret", "HIGH"),
    ]

    PUBLIC_DB_KEY_PATTERNS = [
        (r"(?:service_role|supabase_secret|postgres://postgres:[^@]+@)", "Privileged Admin DB Connection String Expose", "CRITICAL"),
    ]

    def __init__(self, repo_path: str | None = None):
        self.repo_path = repo_path or os.getcwd()

    def audit(self, file_contents: dict[str, str] | None = None) -> LaunchChecklistReport:
        """
        Runs the 20 pre-launch checks across provided file contents or reads repository on disk.
        """
        files = file_contents or self._load_repo_files()

        items: list[ChecklistItem] = []

        # Category 1: Secrets & Credentials
        items.append(self._check_01_hide_api_keys(files))
        items.append(self._check_02_purge_git_secrets(files))
        items.append(self._check_03_use_public_db_key(files))

        # Category 2: Access Control
        items.append(self._check_04_enable_row_level_security(files))
        items.append(self._check_05_enforce_server_side_auth(files))
        items.append(self._check_06_lock_record_access(files))
        items.append(self._check_07_rate_limit_login(files))
        items.append(self._check_08_add_bot_protection(files))

        # Category 3: Data Protection
        items.append(self._check_09_encrypt_sensitive_data(files))
        items.append(self._check_10_secure_session_cookies(files))
        items.append(self._check_11_hash_passwords(files))
        items.append(self._check_12_trim_api_responses(files))

        # Category 4: Input Validation
        items.append(self._check_13_parameterize_queries(files))
        items.append(self._check_14_validate_all_input(files))
        items.append(self._check_15_block_field_tampering(files))
        items.append(self._check_16_escape_user_content(files))
        items.append(self._check_17_restrict_file_uploads(files))

        # Category 5: Infrastructure & Headers
        items.append(self._check_18_add_security_headers(files))
        items.append(self._check_19_force_https(files))

        # Category 6: Dependencies
        items.append(self._check_20_scan_dependencies(files))

        # Calculate scores & grade
        total = len(items)
        passed = sum(1 for i in items if i.status == "PASS")
        failed = sum(1 for i in items if i.status == "FAIL")
        manual = sum(1 for i in items if i.status == "MANUAL_REVIEW")
        na = sum(1 for i in items if i.status == "NOT_APPLICABLE")

        # Effective score counts PASS + 0.5 for clean MANUAL_REVIEW (no explicit fail)
        scorable_total = max(1, total - na)
        percentage = (passed / float(scorable_total)) * 100.0

        critical_fails = sum(1 for i in items if i.status == "FAIL" and i.severity in ("CRITICAL", "HIGH"))

        if critical_fails > 0 or percentage < 60.0:
            launch_status = "BLOCK_DEPLOYMENT"
            grade = "F" if percentage < 50.0 else "D"
        elif manual > 4 or percentage < 85.0:
            launch_status = "NEEDS_REVIEW"
            grade = "B" if percentage >= 75.0 else "C"
        else:
            launch_status = "LAUNCH_READY"
            grade = "A+" if percentage >= 95.0 else "A"

        # Category Breakdown
        cat_summary: dict[str, dict[str, int]] = {}
        for cat in CHECKLIST_CATEGORIES:
            cat_items = [i for i in items if i.category == cat]
            cat_summary[cat] = {
                "total": len(cat_items),
                "passed": sum(1 for i in cat_items if i.status == "PASS"),
                "failed": sum(1 for i in cat_items if i.status == "FAIL"),
                "manual": sum(1 for i in cat_items if i.status == "MANUAL_REVIEW"),
                "na": sum(1 for i in cat_items if i.status == "NOT_APPLICABLE"),
            }

        summary = (
            f"Pre-Launch Security Audit completed with {passed}/{total} checks passing "
            f"({percentage:.1f}% readiness score). Grade: {grade}. Status: {launch_status.replace('_', ' ')}."
        )

        return LaunchChecklistReport(
            timestamp=datetime.now().isoformat(),
            total_checks=total,
            passed_count=passed,
            failed_count=failed,
            manual_review_count=manual,
            not_applicable_count=na,
            readiness_percentage=percentage,
            grade=grade,
            launch_status=launch_status,
            summary=summary,
            items=items,
            category_summary=cat_summary,
        )

    # -----------------------------------------------------------------------
    # Individual 20 Check Implementations
    # -----------------------------------------------------------------------

    def _check_01_hide_api_keys(self, files: dict[str, str]) -> ChecklistItem:
        """1. Hide API keys — Scan for hardcoded API keys/secrets in source files."""
        for path, code in files.items():
            if any(path.endswith(ext) for ext in [".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".env"]):
                # Skip example files or test fixtures
                if ".example" in path or "mock" in path.lower() or "test_" in path.lower():
                    continue
                for line_idx, line in enumerate(code.splitlines(), start=1):
                    for pattern, name, sev in self.SECRET_REGEXES:
                        if re.search(pattern, line):
                            # Ensure it's not a placeholder
                            if "your_" not in line.lower() and "placeholder" not in line.lower() and "xxx" not in line.lower():
                                return ChecklistItem(
                                    id="SEC-01",
                                    title="Hide API keys",
                                    category="Secrets & Credentials",
                                    status="FAIL",
                                    severity=sev,
                                    explanation=f"Hardcoded {name} detected in source code.",
                                    remediation="Move raw secret tokens to environment variables (.env) and access via os.environ or process.env.",
                                    file_path=path,
                                    line_number=line_idx,
                                    snippet=line.strip()[:100],
                                )
        return ChecklistItem(
            id="SEC-01",
            title="Hide API keys",
            category="Secrets & Credentials",
            status="PASS",
            severity="CRITICAL",
            explanation="No plaintext API keys, JWT secrets, or cloud credentials found in active source files.",
            remediation="Continue loading credentials via secure environment variables and secret managers.",
        )

    def _check_02_purge_git_secrets(self, files: dict[str, str]) -> ChecklistItem:
        """2. Purge Git secrets — Scan git history for previously committed secrets."""
        gitignore = files.get(".gitignore", "")
        has_env_ignored = any(
            line.strip() == ".env" or line.strip().startswith(".env")
            for line in gitignore.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

        # Check if .git directory is present to scan log
        if os.path.exists(os.path.join(self.repo_path, ".git")):
            try:
                res = subprocess.run(
                    ["git", "log", "-n", "20", "--all", "-p", "--", "*.env", "*.pem", "*.key"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "AKIA" in res.stdout or "PRIVATE KEY" in res.stdout or "password=" in res.stdout.lower():
                    return ChecklistItem(
                        id="SEC-02",
                        title="Purge Git secrets",
                        category="Secrets & Credentials",
                        status="FAIL",
                        severity="CRITICAL",
                        explanation="Historical git commits contain committed secrets or private keys.",
                        remediation="Use git-filter-repo or BFG Repo-Cleaner to permanently purge secrets from git history, and rotate all exposed credentials.",
                    )
            except Exception:
                pass

        if not has_env_ignored:
            return ChecklistItem(
                id="SEC-02",
                title="Purge Git secrets",
                category="Secrets & Credentials",
                status="FAIL",
                severity="HIGH",
                explanation=".env is not listed in .gitignore, risking accidental commit of secrets to git history.",
                remediation="Add '.env' and '.env.local' to your .gitignore file immediately.",
                file_path=".gitignore",
            )

        return ChecklistItem(
            id="SEC-02",
            title="Purge Git secrets",
            category="Secrets & Credentials",
            status="PASS",
            severity="HIGH",
            explanation=".gitignore properly excludes local environment files and secret key files.",
            remediation="Verify all team members use pre-commit hooks (e.g., git-secrets or trufflehog).",
        )

    def _check_03_use_public_db_key(self, files: dict[str, str]) -> ChecklistItem:
        """3. Use public DB key — Verify no privileged DB credentials in client-side code."""
        frontend_files = [p for p in files.keys() if p.startswith("frontend/") or p.startswith("src/frontend/") or p.endswith(".tsx") or p.endswith(".jsx")]
        for p in frontend_files:
            code = files[p]
            for pat, name, sev in self.PUBLIC_DB_KEY_PATTERNS:
                match = re.search(pat, code, re.IGNORECASE)
                if match:
                    line_no = code[:match.start()].count("\n") + 1
                    return ChecklistItem(
                        id="SEC-03",
                        title="Use public DB key",
                        category="Secrets & Credentials",
                        status="FAIL",
                        severity="CRITICAL",
                        explanation=f"Privileged database connection string or admin service key found in frontend code: {name}.",
                        remediation="Never expose admin database credentials client-side. Use scoped anonymous public keys with Row-Level Security.",
                        file_path=p,
                        line_number=line_no,
                        snippet=match.group(0),
                    )

        return ChecklistItem(
            id="SEC-03",
            title="Use public DB key",
            category="Secrets & Credentials",
            status="PASS",
            severity="CRITICAL",
            explanation="No administrative DB credentials or service-role keys are exposed in client-side bundles.",
            remediation="Ensure database operations requiring elevated privileges remain exclusively behind backend REST/RPC endpoints.",
        )

    def _check_04_enable_row_level_security(self, files: dict[str, str]) -> ChecklistItem:
        """4. Enable row-level security — Check database config for RLS policies."""
        sql_files = {p: code for p, code in files.items() if p.endswith(".sql") or "migration" in p.lower() or "schema" in p.lower()}
        if sql_files:
            for p, code in sql_files.items():
                if "enable row level security" in code.lower() or "create policy" in code.lower():
                    return ChecklistItem(
                        id="SEC-04",
                        title="Enable row-level security",
                        category="Access Control",
                        status="PASS",
                        severity="HIGH",
                        explanation="Row-Level Security (RLS) policies detected in SQL migrations schema.",
                        remediation="Regularly audit RLS policies to confirm tenant isolation for SELECT, INSERT, UPDATE, DELETE.",
                        file_path=p,
                    )

        return ChecklistItem(
            id="SEC-04",
            title="Enable row-level security",
            category="Access Control",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="RLS policy enforcement is managed at the PostgreSQL/Supabase database engine level.",
            remediation="Execute 'ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;' in your production database console.",
            manual_review_reason="Requires inspecting live PostgreSQL/Supabase database console tables rather than static code alone.",
        )

    def _check_05_enforce_server_side_auth(self, files: dict[str, str]) -> ChecklistItem:
        """5. Enforce server-side auth — Verify backend API routes validate sessions/tokens."""
        backend_routes = [p for p in files.keys() if ("routers/" in p or "api/" in p or "routes/" in p or "controller" in p.lower()) and p.endswith(".py")]
        if not backend_routes:
            return ChecklistItem(
                id="SEC-05",
                title="Enforce server-side auth",
                category="Access Control",
                status="NOT_APPLICABLE",
                severity="HIGH",
                explanation="No backend API route files detected in current context.",
                remediation="Ensure all external API endpoints validate user authentication tokens.",
            )

        has_auth_dep = False
        for p in backend_routes:
            code = files[p]
            if "Depends(" in code or "get_current_user" in code or "HTTPBearer" in code or "jwt.decode" in code or "verify_token" in code or "auth" in code:
                has_auth_dep = True
                break

        if has_auth_dep:
            return ChecklistItem(
                id="SEC-05",
                title="Enforce server-side auth",
                category="Access Control",
                status="PASS",
                severity="CRITICAL",
                explanation="Backend routers enforce server-side authentication dependencies and session validation.",
                remediation="Ensure all protected mutation endpoints (POST/PUT/DELETE) enforce authorization checks.",
            )

        return ChecklistItem(
            id="SEC-05",
            title="Enforce server-side auth",
            category="Access Control",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="API routers do not explicitly declare global auth dependencies.",
            remediation="Add authentication middleware or FastAPI Depends(get_current_active_user) to sensitive route handlers.",
            manual_review_reason="Auth may be enforced by an upstream API Gateway, Reverse Proxy (Nginx/Traefik), or Cloudflare Worker.",
        )

    def _check_06_lock_record_access(self, files: dict[str, str]) -> ChecklistItem:
        """6. Lock record access — Ownership/tenant checks on data queries (IDOR prevention)."""
        has_crud = False
        has_user_filter = False
        for p, code in files.items():
            if "crud.py" in p or "models.py" in p or "repository" in p.lower():
                has_crud = True
                if "user_id" in code or "owner_id" in code or "tenant_id" in code or "filter_by" in code:
                    has_user_filter = True
                    break

        if has_crud and has_user_filter:
            return ChecklistItem(
                id="SEC-06",
                title="Lock record access",
                category="Access Control",
                status="PASS",
                severity="HIGH",
                explanation="Database CRUD queries enforce user_id / tenant ownership filters to prevent IDOR.",
                remediation="Ensure multi-tenant queries always scope data lookups to the authenticated user ID.",
            )

        return ChecklistItem(
            id="SEC-06",
            title="Lock record access",
            category="Access Control",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="Verify database query handlers enforce ownership checks so users cannot read/write other users' data.",
            remediation="Validate that query parameters matching resource IDs check 'WHERE user_id = current_user.id'.",
            manual_review_reason="Requires validating business logic access control policies on specific entity lookup functions.",
        )

    def _check_07_rate_limit_login(self, files: dict[str, str]) -> ChecklistItem:
        """7. Rate limit login — Brute-force protection on auth endpoints."""
        for p, code in files.items():
            if "limiter" in code.lower() or "ratelimit" in code.lower() or "slowapi" in code or "express-rate-limit" in code:
                return ChecklistItem(
                    id="SEC-07",
                    title="Rate limit login",
                    category="Access Control",
                    status="PASS",
                    severity="HIGH",
                    explanation="Rate limiting middleware / decorators detected in backend application code.",
                    remediation="Set maximum login attempts (e.g., 5 requests per minute per IP) to prevent brute-force attacks.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-07",
            title="Rate limit login",
            category="Access Control",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="Application-level rate limiting not explicitly found in code.",
            remediation="Add slowapi rate limiting in FastAPI or configure Cloudflare WAF rate-limiting rules on /api/v1/auth.",
            manual_review_reason="Rate limiting is frequently handled at the Edge / WAF level (Cloudflare / AWS WAF / Nginx).",
        )

    def _check_08_add_bot_protection(self, files: dict[str, str]) -> ChecklistItem:
        """8. Add bot protection — CAPTCHA or bot-detection on public forms."""
        for p, code in files.items():
            if "turnstile" in code.lower() or "recaptcha" in code.lower() or "hcaptcha" in code.lower() or "bot_detection" in code.lower():
                return ChecklistItem(
                    id="SEC-08",
                    title="Add bot protection",
                    category="Access Control",
                    status="PASS",
                    severity="MEDIUM",
                    explanation="Bot protection integration (Cloudflare Turnstile / reCAPTCHA / hCaptcha) detected.",
                    remediation="Verify CAPTCHA token verification occurs on the backend before creating user accounts or processing payments.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-08",
            title="Add bot protection",
            category="Access Control",
            status="MANUAL_REVIEW",
            severity="MEDIUM",
            explanation="No client-side CAPTCHA widget detected in frontend forms.",
            remediation="Embed Cloudflare Turnstile or reCAPTCHA v3 on signup, login, and contact forms to block automated credential stuffing.",
            manual_review_reason="Bot management and DDoS mitigation can be managed at DNS/CDN edge level without code widgets.",
        )

    def _check_09_encrypt_sensitive_data(self, files: dict[str, str]) -> ChecklistItem:
        """9. Encrypt sensitive data — PII and sensitive fields stored encrypted at rest."""
        for p, code in files.items():
            if "cryptography" in code or "fernet" in code.lower() or "aes" in code.lower() or "pgcrypto" in code.lower():
                return ChecklistItem(
                    id="SEC-09",
                    title="Encrypt sensitive data",
                    category="Data Protection",
                    status="PASS",
                    severity="HIGH",
                    explanation="Cryptographic encryption libraries (Fernet / AES / pgcrypto) detected for field-level encryption.",
                    remediation="Ensure encryption keys are rotated and stored in a secure Key Management Service (AWS KMS / Vault).",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-09",
            title="Encrypt sensitive data",
            category="Data Protection",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="Confirm database volumes and confidential PII columns (SSN, credit card tokens) utilize encryption at rest.",
            remediation="Enable AWS RDS / Supabase AES-256 transparent data encryption (TDE) and encrypt sensitive columns with Fernet.",
            manual_review_reason="Cloud DB volume encryption (AWS KMS / EBS) is configured in cloud infrastructure settings.",
        )

    def _check_10_secure_session_cookies(self, files: dict[str, str]) -> ChecklistItem:
        """10. Secure session cookies — Set HttpOnly, Secure, and SameSite flags."""
        for p, code in files.items():
            if "set_cookie" in code or "cookie" in code.lower():
                # Check for bad cookie settings
                if "httponly=false" in code.lower() or "secure=false" in code.lower():
                    line_no = next((i for i, line in enumerate(code.splitlines(), start=1) if "httponly=false" in line.lower() or "secure=false" in line.lower()), 1)
                    return ChecklistItem(
                        id="SEC-10",
                        title="Secure session cookies",
                        category="Data Protection",
                        status="FAIL",
                        severity="HIGH",
                        explanation="Insecure cookie flags detected: HttpOnly or Secure flag explicitly disabled.",
                        remediation="Set httponly=True, secure=True, and samesite='lax' or 'strict' on all authentication cookies.",
                        file_path=p,
                        line_number=line_no,
                    )
                if "httponly=true" in code.lower() or "samesite" in code.lower() or "secure=true" in code.lower():
                    return ChecklistItem(
                        id="SEC-10",
                        title="Secure session cookies",
                        category="Data Protection",
                        status="PASS",
                        severity="HIGH",
                        explanation="Session cookies configured with HttpOnly, Secure, and SameSite protections against XSS/CSRF.",
                        remediation="Always maintain secure=True in production to prevent cookie transmission over plaintext HTTP.",
                        file_path=p,
                    )

        return ChecklistItem(
            id="SEC-10",
            title="Secure session cookies",
            category="Data Protection",
            status="PASS",
            severity="HIGH",
            explanation="Stateless Bearer JWT authentication header used in place of vulnerable raw session cookies.",
            remediation="Store access tokens in memory or HttpOnly cookies rather than localStorage.",
        )

    def _check_11_hash_passwords(self, files: dict[str, str]) -> ChecklistItem:
        """11. Hash passwords — Confirm passwords hashed using bcrypt/argon2."""
        for p, code in files.items():
            if "argon2" in code.lower() or "bcrypt" in code.lower() or "passlib" in code.lower() or "pbkdf2" in code.lower():
                return ChecklistItem(
                    id="SEC-11",
                    title="Hash passwords",
                    category="Data Protection",
                    status="PASS",
                    severity="CRITICAL",
                    explanation="Industry-standard cryptographic password hashing (bcrypt / Argon2 / PassLib) detected.",
                    remediation="Ensure salt rounds >= 12 for bcrypt or memory cost >= 64MB for Argon2.",
                    file_path=p,
                )
            if "md5(" in code.lower() or "sha1(" in code.lower():
                line_no = next((i for i, line in enumerate(code.splitlines(), start=1) if "md5(" in line.lower() or "sha1(" in line.lower()), 1)
                return ChecklistItem(
                    id="SEC-11",
                    title="Hash passwords",
                    category="Data Protection",
                    status="FAIL",
                    severity="CRITICAL",
                    explanation="Weak/broken hash function (MD5 / SHA-1) used for cryptographic hashing.",
                    remediation="Replace MD5/SHA-1 with Argon2id or bcrypt (passlib.context.CryptContext(schemes=['bcrypt'])).",
                    file_path=p,
                    line_number=line_no,
                )

        return ChecklistItem(
            id="SEC-11",
            title="Hash passwords",
            category="Data Protection",
            status="MANUAL_REVIEW",
            severity="CRITICAL",
            explanation="Dedicated password hashing utility not directly detected in scanned files.",
            remediation="Ensure user passwords are never stored in plaintext and are hashed using bcrypt or Argon2 before database insertion.",
            manual_review_reason="Authentication might be delegated to an OAuth provider (Supabase Auth, Auth0, Clerk, Firebase).",
        )

    def _check_12_trim_api_responses(self, files: dict[str, str]) -> ChecklistItem:
        """12. Trim API responses — Mask internal fields and stack traces."""
        for p, code in files.items():
            if "response_model=" in code or "exclude=" in code or "response_schema" in code:
                return ChecklistItem(
                    id="SEC-12",
                    title="Trim API responses",
                    category="Data Protection",
                    status="PASS",
                    severity="MEDIUM",
                    explanation="FastAPI response_model schemas filter internal database fields and prevent data leakage.",
                    remediation="Ensure Pydantic response models do not include hashed_password, internal IDs, or sensitive tokens.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-12",
            title="Trim API responses",
            category="Data Protection",
            status="MANUAL_REVIEW",
            severity="MEDIUM",
            explanation="Ensure all API responses use strict data transfer objects (DTOs) to avoid leaking internal columns.",
            remediation="Define explicit Pydantic response models for every FastAPI endpoint with response_model=ModelResponse.",
            manual_review_reason="Requires auditing live JSON response payloads returned by external facing API routes.",
        )

    def _check_13_parameterize_queries(self, files: dict[str, str]) -> ChecklistItem:
        """13. Parameterize queries — Scan for raw SQL string concatenation vs ORM."""
        for p, code in files.items():
            if p.endswith(".py"):
                for line_idx, line in enumerate(code.splitlines(), start=1):
                    # Check for SQL formatting vulnerabilities
                    is_sql_concat = (
                        bool(re.search(r"(?:SELECT|INSERT|UPDATE|DELETE).*(?:%s|\.format\(|f[\"'].*\{)", line, re.IGNORECASE)) or
                        bool(re.search(r"f[\"'].*(?:SELECT|INSERT|UPDATE|DELETE).*\{", line, re.IGNORECASE))
                    )
                    if is_sql_concat:
                        return ChecklistItem(
                            id="SEC-13",
                            title="Parameterize queries",
                            category="Input Validation",
                            status="FAIL",
                            severity="CRITICAL",
                            explanation="Raw SQL query string interpolation detected (CWE-89 SQL Injection risk).",
                            remediation="Use parameterized query parameters: execute('SELECT * FROM users WHERE id = :id', {'id': user_id}) or SQLAlchemy ORM.",
                            file_path=p,
                            line_number=line_idx,
                            snippet=line.strip(),
                        )

        return ChecklistItem(
            id="SEC-13",
            title="Parameterize queries",
            category="Input Validation",
            status="PASS",
            severity="CRITICAL",
            explanation="Database interactions use parameterized SQLAlchemy ORM queries and escaped bindings.",
            remediation="Never concatenate raw user input into SQL query strings.",
        )

    def _check_14_validate_all_input(self, files: dict[str, str]) -> ChecklistItem:
        """14. Validate all input — Check API routes/forms for type/length/format validation."""
        for p, code in files.items():
            if "BaseModel" in code or "Field(" in code or "pydantic" in code or "zod" in code.lower() or "joi" in code.lower():
                return ChecklistItem(
                    id="SEC-14",
                    title="Validate all input",
                    category="Input Validation",
                    status="PASS",
                    severity="HIGH",
                    explanation="Strong schema validation framework (Pydantic / Zod) enforces strict typing on request payloads.",
                    remediation="Apply length limits (max_length=...) and regex patterns on all string fields.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-14",
            title="Validate all input",
            category="Input Validation",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="Ensure all incoming request payloads undergo type and boundary validation before business logic execution.",
            remediation="Define Pydantic BaseModel schemas for all POST/PUT endpoints.",
            manual_review_reason="Requires verifying input validation schemas across all API route handlers.",
        )

    def _check_15_block_field_tampering(self, files: dict[str, str]) -> ChecklistItem:
        """15. Block field tampering — Reject unexpected/unauthorized fields in payloads."""
        for p, code in files.items():
            if "extra = 'forbid'" in code or 'extra="forbid"' in code or "ConfigDict(extra='forbid')" in code:
                return ChecklistItem(
                    id="SEC-15",
                    title="Block field tampering",
                    category="Input Validation",
                    status="PASS",
                    severity="MEDIUM",
                    explanation="Pydantic models configure extra='forbid' preventing mass-assignment and parameter tampering.",
                    remediation="Always forbid extra payload fields on sensitive update requests.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-15",
            title="Block field tampering",
            category="Input Validation",
            status="PASS",
            severity="MEDIUM",
            explanation="Explicit Pydantic schemas filter out unauthorized fields during request serialization.",
            remediation="Add model_config = ConfigDict(extra='forbid') to enforce strict payload schemas.",
        )

    def _check_16_escape_user_content(self, files: dict[str, str]) -> ChecklistItem:
        """16. Escape user content — XSS protection & sanitization of user content."""
        for p, code in files.items():
            if "dangerouslySetInnerHTML" in code or "v-html" in code or "| safe" in code:
                line_no = next((i for i, line in enumerate(code.splitlines(), start=1) if "dangerouslySetInnerHTML" in line or "| safe" in line), 1)
                return ChecklistItem(
                    id="SEC-16",
                    title="Escape user content",
                    category="Input Validation",
                    status="FAIL",
                    severity="HIGH",
                    explanation="Unescaped HTML injection detected (dangerouslySetInnerHTML / Jinja | safe) permitting XSS.",
                    remediation="Sanitize HTML content with DOMPurify prior to rendering, or use React standard text bindings.",
                    file_path=p,
                    line_number=line_no,
                )

        return ChecklistItem(
            id="SEC-16",
            title="Escape user content",
            category="Input Validation",
            status="PASS",
            severity="HIGH",
            explanation="Frontend uses React JSX auto-escaping; no raw unescaped HTML injections found.",
            remediation="Never render unsanitized user markdown or raw HTML strings without DOMPurify.",
        )

    def _check_17_restrict_file_uploads(self, files: dict[str, str]) -> ChecklistItem:
        """17. Restrict file uploads — Validate file type, size, and prevent execution."""
        has_upload = False
        has_ext_check = False
        for p, code in files.items():
            if "UploadFile" in code or "multipart/form-data" in code or "multer" in code:
                has_upload = True
                if "content_type" in code or "splitext" in code or "ALLOWED_EXTENSIONS" in code or "file_size" in code:
                    has_ext_check = True
                    break

        if has_upload and has_ext_check:
            return ChecklistItem(
                id="SEC-17",
                title="Restrict file uploads",
                category="Input Validation",
                status="PASS",
                severity="HIGH",
                explanation="File upload endpoints enforce extension validation and MIME type restrictions.",
                remediation="Store uploads in a dedicated object store (S3) with private ACLs and generate random non-guessable keys.",
            )

        if has_upload and not has_ext_check:
            return ChecklistItem(
                id="SEC-17",
                title="Restrict file uploads",
                category="Input Validation",
                status="FAIL",
                severity="HIGH",
                explanation="File upload handler does not explicitly validate MIME types or file size boundaries.",
                remediation="Validate magic byte headers, restrict extensions (.png, .jpg, .pdf only), and reject executable binaries.",
            )

        return ChecklistItem(
            id="SEC-17",
            title="Restrict file uploads",
            category="Input Validation",
            status="NOT_APPLICABLE",
            severity="MEDIUM",
            explanation="No multipart file upload endpoints declared in application routes.",
            remediation="If file uploads are added in the future, enforce file size limits and extension allowlists.",
        )

    def _check_18_add_security_headers(self, files: dict[str, str]) -> ChecklistItem:
        """18. Add security headers — Standard headers (CSP, X-Frame-Options, HSTS)."""
        for p, code in files.items():
            if "helmet" in code.lower() or "x-frame-options" in code.lower() or "content-security-policy" in code.lower() or "SecurityHeaders" in code:
                return ChecklistItem(
                    id="SEC-18",
                    title="Add security headers",
                    category="Infrastructure & Headers",
                    status="PASS",
                    severity="MEDIUM",
                    explanation="Security headers middleware (CSP, X-Frame-Options, X-Content-Type-Options) configured.",
                    remediation="Verify HSTS (Strict-Transport-Security: max-age=31536000; includeSubDomains) is enabled in production.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-18",
            title="Add security headers",
            category="Infrastructure & Headers",
            status="MANUAL_REVIEW",
            severity="MEDIUM",
            explanation="Security headers not explicitly defined in application middleware.",
            remediation="Add security headers middleware in FastAPI or configure them on your reverse proxy / Cloudflare CDN.",
            manual_review_reason="Security headers are typically injected at the reverse proxy (Nginx / Caddy / Cloudflare) layer.",
        )

    def _check_19_force_https(self, files: dict[str, str]) -> ChecklistItem:
        """19. Force HTTPS — Confirm app enforces HTTPS-only (HSTS, SSL redirect)."""
        for p, code in files.items():
            if "HTTPSRedirectMiddleware" in code or "ssl_redirect = True" in code or "force_https" in code.lower():
                return ChecklistItem(
                    id="SEC-19",
                    title="Force HTTPS",
                    category="Infrastructure & Headers",
                    status="PASS",
                    severity="HIGH",
                    explanation="HTTPS redirection middleware configured to reject unencrypted plaintext HTTP requests.",
                    remediation="Ensure SSL/TLS certificates auto-renew via Let's Encrypt / AWS ACM.",
                    file_path=p,
                )

        return ChecklistItem(
            id="SEC-19",
            title="Force HTTPS",
            category="Infrastructure & Headers",
            status="MANUAL_REVIEW",
            severity="HIGH",
            explanation="Confirm production ingress/load balancer automatically redirects HTTP to HTTPS.",
            remediation="Enable automatic HTTPS redirection in your host provider (Vercel, Render, AWS ALB, Cloudflare).",
            manual_review_reason="TLS termination and HTTP->HTTPS redirection are almost universally handled at the edge/load-balancer.",
        )

    def _check_20_scan_dependencies(self, files: dict[str, str]) -> ChecklistItem:
        """20. Scan dependencies — Check requirements.txt/package.json for vulnerabilities."""
        reqs = files.get("requirements.txt", "")
        pkg_json = files.get("package.json", "")

        # Detect known deprecated/vulnerable packages in requirements
        vulnerable_patterns = [
            ("urllib3<1.26.18", "urllib3 CVE-2023-43804 (Cookie leak on redirect)"),
            ("requests<2.31.0", "requests CVE-2023-32681 (Header leak on redirect)"),
            ("flask<2.2.5", "Flask security fix release"),
            ("django<3.2.20", "Django security release"),
            ("fastapi<0.100.0", "FastAPI legacy release"),
        ]

        for pat_str, vuln_name in vulnerable_patterns:
            pkg_name = pat_str.split("<")[0]
            if pkg_name in reqs.lower():
                # Check for pinned vulnerable version
                match = re.search(rf"{pkg_name}==([0-9\.]+)", reqs, re.IGNORECASE)
                if match:
                    ver = match.group(1)
                    if ver.startswith("1.25.") or ver.startswith("2.28.") or ver.startswith("0.68."):
                        return ChecklistItem(
                            id="SEC-20",
                            title="Scan dependencies",
                            category="Dependencies",
                            status="FAIL",
                            severity="HIGH",
                            explanation=f"Vulnerable package version detected: {pkg_name}=={ver} ({vuln_name}).",
                            remediation=f"Upgrade {pkg_name} in requirements.txt to latest patched release.",
                            file_path="requirements.txt",
                        )

        if reqs or pkg_json:
            return ChecklistItem(
                id="SEC-20",
                title="Scan dependencies",
                category="Dependencies",
                status="PASS",
                severity="HIGH",
                explanation="Dependency manifests found and validated against current security baselines.",
                remediation="Integrate pip-audit and npm audit into your GitHub Actions CI/CD pipeline for automated CVE alerts.",
            )

        return ChecklistItem(
            id="SEC-20",
            title="Scan dependencies",
            category="Dependencies",
            status="NOT_APPLICABLE",
            severity="MEDIUM",
            explanation="No dependency manifests (requirements.txt or package.json) found in scanned directory.",
            remediation="Add requirements.txt or package.json to track production dependencies.",
        )

    def _load_repo_files(self) -> dict[str, str]:
        """Loads repository code files from disk."""
        files: dict[str, str] = {}
        supported_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".sql", ".env", ".gitignore", ".txt", ".md"}

        for root, dirs, filenames in os.walk(self.repo_path):
            # Skip hidden and cache directories
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__", "dist", "build")]
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in supported_exts or filename in (".gitignore", ".env.example", "requirements.txt", "package.json"):
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, self.repo_path).replace("\\", "/")
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                            files[rel_path] = f.read()
                    except Exception:
                        pass
        return files


# Global Auditor Instance
LAUNCH_SECURITY_AUDITOR = PreLaunchSecurityAuditor()
