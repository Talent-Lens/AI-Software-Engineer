"""
Unit tests for GitHub URL and CVE Commit Resolver (src/benchmarks/cve_resolver.py)
"""
import pytest
from src.benchmarks_research.cve_resolver import (
    parse_and_validate_github_url,
    extract_commit_from_github_url,
    extract_cve_or_advisory_or_commit,
    validate_commit_sha,
    resolve_cve_or_advisory,
    ResolverError,
)


def test_validate_github_url():
    owner, repo = parse_and_validate_github_url("https://github.com/pallets/flask")
    assert owner == "pallets"
    assert repo == "flask"

    owner2, repo2 = parse_and_validate_github_url("https://github.com/psf/requests.git")
    assert owner2 == "psf"
    assert repo2 == "requests"

    # Support direct commit URLs
    owner3, repo3 = parse_and_validate_github_url("https://github.com/psf/requests/commit/c45d7c49ea75133e52ab22a8e9e13173938e36ff")
    assert owner3 == "psf"
    assert repo3 == "requests"
    assert extract_commit_from_github_url("https://github.com/psf/requests/commit/c45d7c49ea75133e52ab22a8e9e13173938e36ff") == "c45d7c49ea75133e52ab22a8e9e13173938e36ff"

    # Extraction of CVE from NVD / Advisory URLs
    nvd_url = "https://nvd.nist.gov/vuln/detail/CVE-2018-18074"
    assert extract_cve_or_advisory_or_commit(nvd_url) == "CVE-2018-18074"

    ghsa_url = "https://github.com/advisories/GHSA-wqvq-5x8w-62x8"
    assert extract_cve_or_advisory_or_commit(ghsa_url) == "GHSA-WQVQ-5X8W-62X8"

    commit_url = "https://github.com/psf/requests/commit/c45d7c49ea75133e52ab22a8e9e13173938e36ff"
    assert extract_cve_or_advisory_or_commit(commit_url) == "c45d7c49ea75133e52ab22a8e9e13173938e36ff"

    # Invalid URLs
    with pytest.raises(ResolverError):
        parse_and_validate_github_url("http://insecure-site.com/foo/bar")

    with pytest.raises(ResolverError):
        parse_and_validate_github_url("https://github.com/owner/repo/subpath")

    with pytest.raises(ResolverError):
        parse_and_validate_github_url("file:///etc/passwd")


def test_validate_commit_sha():
    valid = "d71912f2c8d281313cae74fecaeae8ce8f4118f6"
    assert validate_commit_sha(valid) == valid

    short = "d71912f"
    assert validate_commit_sha(short) == short

    # Invalid SHAs
    with pytest.raises(ResolverError):
        validate_commit_sha("invalid-sha-123")

    with pytest.raises(ResolverError):
        validate_commit_sha("12345")  # Too short (<7 chars)


def test_resolve_direct_commit_url(monkeypatch):
    from src.benchmarks_research import cve_resolver

    # Mock parent resolution to avoid external GitHub API rate limits during unit tests
    def mock_parent(owner, repo, sha, token=None, local_dir=None):
        return "1111111111111111111111111111111111111111"

    monkeypatch.setattr(cve_resolver, "resolve_commit_parent", mock_parent)

    res = resolve_cve_or_advisory(
        owner="pallets",
        repo="flask",
        identifier="https://github.com/pallets/flask/commit/d71912f2c8d281313cae74fecaeae8ce8f4118f6",
    )
    assert res["fix_commit"] == "d71912f2c8d281313cae74fecaeae8ce8f4118f6"
    assert res["parent_commit"] == "1111111111111111111111111111111111111111"
