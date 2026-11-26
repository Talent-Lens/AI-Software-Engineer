"""
Input Validation and GitHub/CVE Commit Resolver.
Resolves CVE/advisory identifiers and fix commit SHAs to vulnerable parent commits.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ai_engineer.benchmarks.cve_resolver")

GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?(?:/(?:commit|tree|blob|pull)/.*)?/?$",
    re.IGNORECASE
)
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,8}$", re.IGNORECASE)
GHSA_PATTERN = re.compile(r"^GHSA-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}$", re.IGNORECASE)


class ResolverError(Exception):
    """Raised when repository, commit, or CVE resolution fails."""
    pass


def extract_commit_from_github_url(url: str) -> Optional[str]:
    """Extracts commit SHA if present in a GitHub commit URL."""
    if not url:
        return None
    match = re.search(r"/commit/([0-9a-fA-F]{7,40})", url)
    return match.group(1).lower() if match else None


def extract_cve_or_advisory_or_commit(text: str) -> str:
    """
    Extracts a CVE ID, GHSA ID, or commit SHA from user input.
    Robustly handles URLs from NVD, MITRE, GitHub Advisory, or GitHub commit links.
    """
    clean = (text or "").strip()
    if not clean:
        return ""

    # Check for CVE anywhere in text (e.g. from NVD URL: https://nvd.nist.gov/vuln/detail/CVE-2018-18074)
    cve_match = re.search(r"\b(CVE-\d{4}-\d{4,8})\b", clean, re.IGNORECASE)
    if cve_match:
        return cve_match.group(1).upper()

    # Check for GHSA anywhere in text (e.g. https://github.com/advisories/GHSA-xxxx-xxxx-xxxx)
    ghsa_match = re.search(r"\b(GHSA-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4})\b", clean, re.IGNORECASE)
    if ghsa_match:
        return ghsa_match.group(1).upper()

    # Check for commit SHA in commit URL
    commit_match = re.search(r"/commit/([0-9a-fA-F]{7,40})", clean)
    if commit_match:
        return commit_match.group(1).lower()

    if SHA_PATTERN.match(clean):
        return clean.lower()

    return clean


def parse_and_validate_github_url(url: str) -> Tuple[str, str]:
    """
    Validates GitHub HTTPS repository URL.
    Returns (owner, repo).
    Accepts standard repo URLs as well as direct commit/tree URLs (extracting repo).
    Rejects malformed URLs, localhost, file schemes, and shell metacharacters.
    """
    clean_url = (url or "").strip()
    match = GITHUB_URL_PATTERN.match(clean_url)
    if not match:
        raise ResolverError(
            f"Invalid GitHub repository URL: '{url}'. Expected format: https://github.com/<owner>/<repo>"
        )
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def validate_commit_sha(sha: str) -> str:
    """Validates commit SHA format."""
    clean_sha = (sha or "").strip()
    if not SHA_PATTERN.match(clean_sha):
        raise ResolverError(f"Invalid commit SHA: '{sha}'. Must be a 7 to 40-character hexadecimal string.")
    return clean_sha.lower()


def get_github_auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Retrieves standard GitHub headers with optional authorization."""
    gh_token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
    headers = {
        "User-Agent": "CodeGuardian-Benchmark-Engine/2.1",
        "Accept": "application/vnd.github.v3+json",
    }
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token.strip()}"
    return headers


def fetch_github_json(url: str, token: Optional[str] = None, max_retries: int = 3) -> Dict[str, Any]:
    """
    Makes a secure HTTP GET request to GitHub API with automatic exponential retry
    on transient network, socket, or DNS errors (e.g. WinError 11001 getaddrinfo failed).
    """
    import time
    headers = get_github_auth_headers(token)
    req = urllib.request.Request(url, headers=headers)
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ResolverError(f"GitHub resource not found at {url}")
            if e.code == 403:
                raise ResolverError("GitHub API rate limit exceeded. Set GITHUB_TOKEN in .env to increase limit.")
            raise ResolverError(f"GitHub API error {e.code}: {e.reason}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < max_retries - 1:
                sleep_s = (attempt + 1) * 2.0
                logger.warning(
                    "Transient network error connecting to GitHub API (%s). Retrying in %.1fs (attempt %d/%d)...",
                    e, sleep_s, attempt + 1, max_retries
                )
                time.sleep(sleep_s)
            else:
                break
        except Exception as e:
            raise ResolverError(f"Failed to connect to GitHub API: {e}")

    raise ResolverError(
        f"Failed to connect to GitHub API after {max_retries} attempts: {last_err}. "
        "Please check your internet connection and DNS settings."
    )


def resolve_commit_parent(
    owner: str,
    repo: str,
    commit_sha: str,
    github_token: Optional[str] = None,
    local_repo_dir: Optional[Path] = None,
) -> str:
    """
    Resolves the parent commit SHA ($N-1$) of a given commit.
    Uses local git directory if available, otherwise queries GitHub REST API.
    """
    if local_repo_dir and (local_repo_dir / ".git").is_dir():
        try:
            res = subprocess.run(
                ["git", "rev-parse", f"{commit_sha}~1"],
                cwd=str(local_repo_dir),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            logger.debug("Local git parent resolution failed, falling back to API: %s", e)

    # API fallback
    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
    data = fetch_github_json(api_url, github_token)
    parents = data.get("parents", [])
    if not parents:
        raise ResolverError(f"Commit {commit_sha} has no parents (initial root commit). Cannot evaluate fix diff.")
    return parents[0]["sha"].lower()


def resolve_cve_or_advisory(
    owner: str,
    repo: str,
    identifier: str,
    github_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolves a CVE ID (CVE-YYYY-NNNN), GHSA ID, or direct commit SHA to:
    {
      "cve_id": str | None,
      "fix_commit": str,
      "parent_commit": str,
      "cwe": str | None,
      "summary": str,
    }
    """
    clean_id = extract_cve_or_advisory_or_commit(identifier)

    # Case A: User passed a commit SHA directly
    if SHA_PATTERN.match(clean_id):
        fix_sha = validate_commit_sha(clean_id)
        parent_sha = resolve_commit_parent(owner, repo, fix_sha, github_token)
        return {
            "cve_id": None,
            "fix_commit": fix_sha,
            "parent_commit": parent_sha,
            "cwe": None,
            "summary": f"Direct fix commit {fix_sha[:8]}",
        }

    # Case B: User passed a full GitHub commit URL
    # e.g., https://github.com/owner/repo/commit/<sha>
    if "github.com" in clean_id and "/commit/" in clean_id:
        sha_part = clean_id.split("/commit/")[-1].split("/")[0].split("?")[0].split("#")[0]
        fix_sha = validate_commit_sha(sha_part)
        parent_sha = resolve_commit_parent(owner, repo, fix_sha, github_token)
        return {
            "cve_id": None,
            "fix_commit": fix_sha,
            "parent_commit": parent_sha,
            "cwe": None,
            "summary": f"Commit URL {fix_sha[:8]}",
        }

    # Case C: CVE or GHSA advisory resolution
    cwe_found = None
    fix_sha = None
    summary = ""

    # Query GitHub Advisory Database
    advisory_api_url = f"https://api.github.com/advisories?cve_id={clean_id}"
    try:
        data = fetch_github_json(advisory_api_url, github_token)
        if isinstance(data, list) and data:
            adv = data[0]
            from src.benchmarks_research.scope import validate_and_normalize_cwe
            summary = adv.get("summary", "")
            raw_cwes = list(adv.get("cwe_ids") or [])
            for c_obj in adv.get("cwes") or []:
                if isinstance(c_obj, dict) and c_obj.get("cwe_id"):
                    raw_cwes.append(c_obj["cwe_id"])
            for rc in raw_cwes:
                cwe_found = validate_and_normalize_cwe(rc, strict=False)
                if cwe_found:
                    break
            # Search references for commit SHAs on this repo
            refs = adv.get("references", [])
            for ref in refs:
                ref_url = ref if isinstance(ref, str) else ref.get("url", "")
                if f"github.com/{owner}/{repo}/commit/" in ref_url:
                    candidate_sha = ref_url.split("/commit/")[-1].split("/")[0].split("?")[0]
                    if SHA_PATTERN.match(candidate_sha):
                        fix_sha = candidate_sha.lower()
                        break
    except Exception as e:
        logger.debug("GitHub global advisory search failed: %s", e)

    if not fix_sha:
        # Check repo security advisories
        repo_adv_url = f"https://api.github.com/repos/{owner}/{repo}/security-advisories"
        try:
            repo_advisories = fetch_github_json(repo_adv_url, github_token)
            if isinstance(repo_advisories, list):
                for adv in repo_advisories:
                    cve = adv.get("cve_id")
                    ghsa = adv.get("ghsa_id")
                    if (cve and cve.lower() == clean_id.lower()) or (ghsa and ghsa.lower() == clean_id.lower()):
                        cwes = adv.get("cwe_ids", [])
                        if cwes:
                            cwe_found = cwes[0]
                        summary = adv.get("summary", "")
                        break
        except Exception as e:
            logger.debug("Repo security advisory query failed: %s", e)

    if not fix_sha:
        raise ResolverError(
            f"Could not automatically resolve fix commit for advisory '{clean_id}' on {owner}/{repo}. "
            "Please provide the fix commit SHA directly."
        )

    parent_sha = resolve_commit_parent(owner, repo, fix_sha, github_token)
    return {
        "cve_id": clean_id if (CVE_PATTERN.match(clean_id) or GHSA_PATTERN.match(clean_id)) else None,
        "fix_commit": fix_sha,
        "parent_commit": parent_sha,
        "cwe": cwe_found or "unknown",
        "summary": summary or f"Resolved from {clean_id}",
    }
