"""
Ground Truth Loader and CWE Equivalence Validator.
Loads version-controlled benchmark ground truth manifests and resolves CWE parent/child variants.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ai_engineer.benchmarks.ground_truth")


@dataclass
class GroundTruthFinding:
    id: str
    file: str
    line_start: int
    line_end: int
    cwe: str
    severity: str
    label: str  # vulnerable | clean | false-positive-of-tool-X
    source: str  # cve-fix | manual-triage | documented-vuln
    notes: Optional[str] = None


@dataclass
class GroundTruthRepo:
    repo_name: str
    url: str
    pinned_vulnerable_sha: str
    pinned_clean_sha: Optional[str]
    language: str
    loc: int
    description: str
    repo_type: str = "cve_fix"
    labeled_findings: List[GroundTruthFinding] = field(default_factory=list)
    clean_negative_regions: List[Dict[str, Any]] = field(default_factory=list)
    manifest_path: str = ""


class GroundTruthLoader:
    """
    Manages loading of ground-truth manifests and CWE equivalence maps.
    """

    def __init__(self, ground_truth_dir: Optional[Path] = None, cwe_map_path: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parents[2] / "benchmarks" / "ground_truth"
        self.ground_truth_dir = ground_truth_dir or base_dir
        self.cwe_map_path = cwe_map_path or (self.ground_truth_dir / "cwe_map.json")
        self._cwe_alias_to_canonical: Dict[str, str] = {}
        self._cwe_to_family: Dict[str, str] = {}
        self._load_cwe_map()

    def _load_cwe_map(self) -> None:
        """Loads and indexes the CWE equivalence map and top-level family map."""
        if not self.cwe_map_path.exists():
            logger.warning("CWE map file not found at %s. Equivalence will be exact match only.", self.cwe_map_path)
            return

        try:
            with open(self.cwe_map_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            clusters = data.get("canonical_clusters", {})
            for canonical_id, details in clusters.items():
                canonical_clean = self._clean_cwe(canonical_id)
                self._cwe_alias_to_canonical[canonical_clean] = canonical_clean
                for alias in details.get("aliases", []):
                    self._cwe_alias_to_canonical[self._clean_cwe(alias)] = canonical_clean

            families = data.get("family_clusters", {})
            for family_id, details in families.items():
                fam_clean = self._clean_cwe(family_id)
                self._cwe_to_family[fam_clean] = fam_clean
                for member in details.get("members", []):
                    self._cwe_to_family[self._clean_cwe(member)] = fam_clean
        except Exception as e:
            logger.error("Failed to load CWE map: %s", e)

    @staticmethod
    def _clean_cwe(cwe_str: Optional[str]) -> str:
        """Normalizes CWE strings and strips leading zeros, e.g. 'CWE-078' -> 'CWE-78'."""
        if not cwe_str:
            return ""
        s = cwe_str.strip().upper()
        if s.startswith("CWE-") and s[4:].isdigit():
            return f"CWE-{int(s[4:])}"
        if s.isdigit():
            return f"CWE-{int(s)}"
        return s

    def normalize_cwe(self, cwe_str: Optional[str]) -> Optional[str]:
        """Maps any CWE identifier or alias to its canonical CWE cluster ID."""
        cleaned = self._clean_cwe(cwe_str)
        if not cleaned:
            return None
        return self._cwe_alias_to_canonical.get(cleaned, cleaned)

    def normalize_cwe_family(self, cwe_str: Optional[str]) -> Optional[str]:
        """Maps a CWE identifier to its MITRE top-level family cluster (if defined)."""
        cleaned = self._clean_cwe(cwe_str)
        if not cleaned or cleaned == "UNKNOWN":
            return None
        if cleaned in self._cwe_to_family:
            return self._cwe_to_family[cleaned]
        canonical = self.normalize_cwe(cleaned)
        if canonical and canonical in self._cwe_to_family:
            return self._cwe_to_family[canonical]
        return None

    def is_cwe_equivalent(self, cwe_a: Optional[str], cwe_b: Optional[str]) -> bool:
        """
        Determines whether two CWEs belong to the same canonical exact/parent-child cluster.
        """
        if not cwe_a or not cwe_b:
            return False
        norm_a = self.normalize_cwe(cwe_a)
        norm_b = self.normalize_cwe(cwe_b)
        return bool(norm_a and norm_b and norm_a != "UNKNOWN" and norm_a == norm_b)

    def is_cwe_same_family(self, cwe_a: Optional[str], cwe_b: Optional[str]) -> bool:
        """
        Determines whether two CWEs share the same MITRE top-level category/family.
        Kept strictly separate from exact/parent-child equivalence.
        """
        if not cwe_a or not cwe_b:
            return False
        fam_a = self.normalize_cwe_family(cwe_a)
        fam_b = self.normalize_cwe_family(cwe_b)
        return bool(fam_a and fam_b and fam_a == fam_b)

    def load_manifest(self, manifest_path: Path) -> GroundTruthRepo:
        """
        Loads a single repository ground-truth JSON manifest.
        """
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        findings = []
        for raw in data.get("labeled_findings", []):
            findings.append(
                GroundTruthFinding(
                    id=raw["id"],
                    file=raw["file"],
                    line_start=raw["line_start"],
                    line_end=raw.get("line_end", raw["line_start"]),
                    cwe=raw.get("cwe", ""),
                    severity=raw.get("severity", "MEDIUM"),
                    label=raw.get("label", "vulnerable"),
                    source=raw.get("source", "documented-vuln"),
                    notes=raw.get("notes"),
                )
            )

        base_dir = Path(__file__).resolve().parents[2]
        try:
            rel_path = manifest_path.resolve().relative_to(base_dir).as_posix()
        except Exception:
            rel_path = str(manifest_path)

        return GroundTruthRepo(
            repo_name=data["repo_name"],
            url=data["url"],
            pinned_vulnerable_sha=data["pinned_vulnerable_sha"],
            pinned_clean_sha=data.get("pinned_clean_sha"),
            language=data.get("language", "python"),
            loc=data.get("loc", 0),
            description=data.get("description", ""),
            repo_type=data.get("repo_type", "cve_fix"),
            labeled_findings=findings,
            clean_negative_regions=data.get("clean_negative_regions", []),
            manifest_path=rel_path,
        )

    def load_all_manifests(self) -> List[GroundTruthRepo]:
        """Loads all ground-truth manifests from the ground_truth directory (latest version per repo_name)."""
        if not self.ground_truth_dir.exists():
            return []

        by_repo: Dict[str, GroundTruthRepo] = {}
        for p in sorted(self.ground_truth_dir.glob("*.json")):
            if p.name == "cwe_map.json":
                continue
            try:
                m = self.load_manifest(p)
                by_repo[m.repo_name] = m
            except Exception as e:
                logger.error("Error loading manifest %s: %s", p, e)
        return list(by_repo.values())
