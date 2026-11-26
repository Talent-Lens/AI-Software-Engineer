"""
Deterministic Benchmark Evaluator.
Computes the 6 standardized security benchmark metrics against independent ground truth.
"""
from __future__ import annotations

import logging
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional, Set, Tuple

from src.benchmarks_research.ground_truth_loader import GroundTruthFinding, GroundTruthLoader, GroundTruthRepo
from src.benchmarks_research.schema import MetricSummary, NormalizedFinding

logger = logging.getLogger("ai_engineer.benchmarks.evaluator")


def normalize_file_path(path_str: str) -> str:
    """
    Normalizes file path strings across OS separators (Windows vs POSIX)
    and removes common leading directory noise.
    """
    if not path_str:
        return ""
    p = path_str.replace("\\", "/").strip().lstrip("/")
    # Remove leading dots or redundant segments
    parts = [part for part in p.split("/") if part and part != "."]
    return "/".join(parts).lower()


def file_paths_match(file_a: str, file_b: str) -> bool:
    """
    Checks if two normalized file paths refer to the same relative file.
    Supports suffix matching (e.g. 'app/app.py' matches 'repo/app/app.py').
    """
    norm_a = normalize_file_path(file_a)
    norm_b = normalize_file_path(file_b)
    if norm_a == norm_b:
        return True
    return norm_a.endswith("/" + norm_b) or norm_b.endswith("/" + norm_a)


class BenchmarkEvaluator:
    """
    Evaluates normalized findings against research ground truth
    strictly according to the 6 metric definitions.
    """

    def __init__(self, loader: Optional[GroundTruthLoader] = None, max_detection_window: int = 10):
        self.loader = loader or GroundTruthLoader()
        self.max_detection_window = max_detection_window  # Max lines from vuln to be considered candidate TP

    def match_findings(
        self,
        ground_truth: GroundTruthRepo,
        vulnerable_findings: List[NormalizedFinding],
    ) -> Tuple[Dict[int, Tuple[str, Optional[str], int, bool]], Set[str], List[Dict[str, Any]]]:
        """
        Matches vulnerable_findings against labeled_vulns within max_detection_window.
        Returns:
          - finding_matches: {f_idx: ("TP", gt_id, dist, cwe_match)} for matched findings
          - matched_gt_ids: unique ground-truth IDs matched (for Recall)
          - tp_findings_details: per-GT-label best match details (for Localization/Classification)
        """
        labeled_vulns = [f for f in ground_truth.labeled_findings if f.label == "vulnerable"]
        matched_gt_ids: Set[str] = set()
        finding_matches: Dict[int, Tuple[str, Optional[str], int, bool]] = {}
        tp_findings_details: List[Dict[str, Any]] = []

        candidates: List[Tuple[int, int, GroundTruthFinding, NormalizedFinding, int, bool, bool]] = []
        for f_idx, finding in enumerate(vulnerable_findings):
            for gt_vuln in labeled_vulns:
                if file_paths_match(finding.file_path, gt_vuln.file):
                    f_line = finding.line_start
                    if gt_vuln.line_start <= f_line <= gt_vuln.line_end:
                        dist = 0
                    elif f_line < gt_vuln.line_start:
                        dist = gt_vuln.line_start - f_line
                    else:
                        dist = f_line - gt_vuln.line_end

                    cwe_match = self.loader.is_cwe_equivalent(finding.cwe, gt_vuln.cwe)
                    cwe_family_match = self.loader.is_cwe_same_family(finding.cwe, gt_vuln.cwe)

                    if dist <= self.max_detection_window:
                        candidates.append((dist, 0 if cwe_match else 1, gt_vuln, finding, f_idx, cwe_match, cwe_family_match))

        candidates.sort(key=lambda x: (x[0], x[1]))

        for dist, _, gt_vuln, finding, f_idx, cwe_match, cwe_family_match in candidates:
            if f_idx in finding_matches:
                continue

            finding_matches[f_idx] = ("TP", gt_vuln.id, dist, cwe_match)
            if gt_vuln.id not in matched_gt_ids:
                matched_gt_ids.add(gt_vuln.id)
                is_localized = dist <= 3
                tp_findings_details.append({
                    "gt_id": gt_vuln.id,
                    "finding": finding,
                    "distance": dist,
                    "is_localized": is_localized,
                    "cwe_match": cwe_match,
                    "cwe_family_match": cwe_family_match,
                })

        return finding_matches, matched_gt_ids, tp_findings_details

    def evaluate(
        self,
        ground_truth: GroundTruthRepo,
        vulnerable_findings: List[NormalizedFinding],
        clean_findings: Optional[List[NormalizedFinding]] = None,
        duration_s: float = 0.0,
    ) -> MetricSummary:
        """
        Calculates the 6 standardized metrics:
        1. Precision: TP / (TP + FP) on vulnerable code
        2. Recall: TP / (TP + FN) against labeled ground truth
        3. False Positive Rate: Clean-FP per 1,000 LOC on clean code
        4. Line-Level Localization: % of TPs within ±3 lines
        5. Vulnerability Classification: % of TPs matching labeled CWE
        6. Scan Latency: Seconds per 1,000 LOC
        """
        labeled_vulns = [f for f in ground_truth.labeled_findings if f.label == "vulnerable"]
        finding_matches, matched_gt_ids, tp_findings_details = self.match_findings(ground_truth, vulnerable_findings)

        tp = len(matched_gt_ids)
        precision_tp = len(finding_matches)
        fp = len(vulnerable_findings) - precision_tp
        fn = len(labeled_vulns) - tp

        # 1. Precision: precision_tp / (precision_tp + fp) — undefined (None / n/a) when 0 findings reported
        precision = (precision_tp / (precision_tp + fp)) if (precision_tp + fp) > 0 else None

        # 2. Recall: TP / (TP + FN) — 0.0 when labeled vulns exist and none detected
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else None

        # 3. False Positive Rate on clean code (per 1,000 LOC)
        loc = max(ground_truth.loc, 1)
        if clean_findings is not None:
            clean_fp_count = len(clean_findings)
        else:
            clean_fp_count = 0
            # If no clean commit scan was performed, count any findings that hit explicit clean negative regions
            if ground_truth.clean_negative_regions:
                for f in vulnerable_findings:
                    for region in ground_truth.clean_negative_regions:
                        if file_paths_match(f.file_path, region["file"]):
                            if region["line_start"] <= f.line_start <= region["line_end"]:
                                clean_fp_count += 1
                                break

        false_positive_rate = (clean_fp_count / loc) * 1000.0

        # 4. Line-Level Localization: share of TPs within ±3 lines — undefined (None / n/a) when TP == 0
        localized_count = sum(1 for item in tp_findings_details if item["is_localized"])
        localization_accuracy = (localized_count / tp) if tp > 0 else None

        # 5. Vulnerability Classification (kept strictly separate: exact/parent-child vs MITRE family)
        cwe_matched_count = sum(1 for item in tp_findings_details if item["cwe_match"])
        classification_accuracy = (cwe_matched_count / tp) if tp > 0 else None
        cwe_family_matched_count = sum(1 for item in tp_findings_details if item["cwe_family_match"])
        classification_family_accuracy = (cwe_family_matched_count / tp) if tp > 0 else None

        # 6. Scan Latency: vulnerable-commit-only seconds per 1,000 in-scope LOC
        # (ensures apples-to-apples comparison across single-commit and dual-commit repos)
        scan_latency = (duration_s / loc) * 1000.0 if duration_s > 0 else 0.0

        counts = {
            "tp": tp,
            "precision_tp": precision_tp,
            "fp": fp,
            "fn": fn,
            "total_labeled_vulns": len(labeled_vulns),
            "total_vulnerable_findings": len(vulnerable_findings),
            "clean_fp": clean_fp_count,
            "localized_count": localized_count,
            "cwe_matched_count": cwe_matched_count,
            "cwe_family_matched_count": cwe_family_matched_count,
            "classification_family_accuracy": round(classification_family_accuracy, 4) if classification_family_accuracy is not None else None,
            "loc": loc,
            "duration_s": round(duration_s, 2),
            "latency_basis": "vulnerable_commit_only",
        }

        return MetricSummary(
            precision=precision,
            recall=recall,
            false_positive_rate=false_positive_rate,
            localization_accuracy=localization_accuracy,
            classification_accuracy=classification_accuracy,
            classification_family_accuracy=classification_family_accuracy,
            scan_latency=scan_latency,
            counts=counts,
        )
