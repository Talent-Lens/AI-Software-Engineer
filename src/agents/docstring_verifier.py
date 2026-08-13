"""
Docstring Accuracy Verifier Agent (TASK-E5)

Audits generated or existing code documentation against AST function signatures
(parameter names, type annotations, default values, and return types) to eliminate
docstring hallucinations and type mismatches.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import requests

from src.schema import AgentResponse

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class FunctionParam:
    name: str
    type_annotation: str | None = None
    default_value: str | None = None
    is_args: bool = False
    is_kwargs: bool = False


@dataclass
class FunctionSignature:
    name: str
    params: list[FunctionParam] = field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None

    def get_param_names(self) -> list[str]:
        return [p.name for p in self.params if p.name not in ("self", "cls")]


@dataclass
class ParsedDocParam:
    name: str
    type_desc: str | None = None
    description: str = ""


@dataclass
class ParsedDocstring:
    summary: str = ""
    params: dict[str, ParsedDocParam] = field(default_factory=dict)
    returns_type: str | None = None
    returns_desc: str | None = None
    raises: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DocstringDiscrepancy:
    discrepancy_type: str  # "HALLUCINATED_PARAM" | "MISSING_PARAM" | "TYPE_MISMATCH" | "DEFAULT_VALUE_MISMATCH" | "RETURN_TYPE_MISMATCH"
    param_name: str | None
    description: str
    expected: str | None = None
    actual: str | None = None
    severity: str = "High"  # "High" | "Medium" | "Low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "discrepancy_type": self.discrepancy_type,
            "param_name": self.param_name,
            "description": self.description,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
        }


@dataclass
class DocstringAccuracyReport:
    status: str  # "PASS" | "FAIL"
    score: int  # 0 to 100
    summary: str
    function_name: str
    signature_summary: str
    discrepancies: list[DocstringDiscrepancy] = field(default_factory=list)
    suggested_docstring: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "summary": self.summary,
            "function_name": self.function_name,
            "signature_summary": self.signature_summary,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "suggested_docstring": self.suggested_docstring,
        }

    def to_markdown(self) -> str:
        status_icon = "[PASS]" if self.status == "PASS" else "[FAIL]"
        lines = [
            f"# Docstring Accuracy Report: `{self.function_name}`",
            f"",
            f"**Overall Status:** {status_icon} | **Accuracy Score:** `{self.score}/100`",
            f"",
            f"**Signature:** `{self.signature_summary}`",
            f"",
            f"**Summary:** {self.summary}",
            f"",
        ]

        if self.discrepancies:
            lines.append("### Detected Discrepancies & Hallucinations")
            lines.append("| Type | Param / Target | Severity | Description | Expected | Actual |")
            lines.append("|---|---|---|---|---|---|")
            for d in self.discrepancies:
                p_target = d.param_name or "N/A"
                exp = d.expected or "N/A"
                act = d.actual or "N/A"
                lines.append(
                    f"| {d.discrepancy_type} | {p_target} | **{d.severity.upper()}** | {d.description} | `{exp}` | `{act}` |"
                )
            lines.append("")

        if self.suggested_docstring:
            lines.append("### Corrected Ground-Truth Docstring")
            lines.append(f"```python\n{self.suggested_docstring}\n```")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AST Signature Extractor
# ---------------------------------------------------------------------------

class ASTSignatureExtractor:
    """
    Extracts ground-truth function signatures (parameters, types, defaults, return hints)
    from Python AST nodes or source strings.
    """

    @staticmethod
    def extract_from_code(func_code: str) -> FunctionSignature | None:
        clean_code = func_code.strip()
        if not clean_code:
            return None

        try:
            tree = ast.parse(clean_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return ASTSignatureExtractor.extract_from_node(node)
        except SyntaxError:
            pass

        return None

    @staticmethod
    def extract_from_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionSignature:
        func_name = node.name
        docstring = ast.get_docstring(node)

        params: list[FunctionParam] = []
        args_obj = node.args

        # Positional defaults alignment
        # Defaults are aligned from the end of args
        num_args = len(args_obj.args)
        num_defaults = len(args_obj.defaults)
        default_offset = num_args - num_defaults

        for idx, arg in enumerate(args_obj.args):
            p_name = arg.arg
            type_ann = ASTSignatureExtractor._unparse(arg.annotation) if arg.annotation else None

            default_val = None
            if idx >= default_offset:
                def_node = args_obj.defaults[idx - default_offset]
                default_val = ASTSignatureExtractor._unparse(def_node)

            params.append(
                FunctionParam(
                    name=p_name,
                    type_annotation=type_ann,
                    default_value=default_val,
                )
            )

        if args_obj.vararg:
            p_name = f"*{args_obj.vararg.arg}"
            type_ann = ASTSignatureExtractor._unparse(args_obj.vararg.annotation) if args_obj.vararg.annotation else None
            params.append(FunctionParam(name=p_name, type_annotation=type_ann, is_args=True))

        for idx, kwarg_node in enumerate(args_obj.kwonlyargs):
            p_name = kwarg_node.arg
            type_ann = ASTSignatureExtractor._unparse(kwarg_node.annotation) if kwarg_node.annotation else None
            default_val = None
            if idx < len(args_obj.kw_defaults) and args_obj.kw_defaults[idx] is not None:
                default_val = ASTSignatureExtractor._unparse(args_obj.kw_defaults[idx])

            params.append(
                FunctionParam(
                    name=p_name,
                    type_annotation=type_ann,
                    default_value=default_val,
                )
            )

        if args_obj.kwarg:
            p_name = f"**{args_obj.kwarg.arg}"
            type_ann = ASTSignatureExtractor._unparse(args_obj.kwarg.annotation) if args_obj.kwarg.annotation else None
            params.append(FunctionParam(name=p_name, type_annotation=type_ann, is_kwargs=True))

        return_type = ASTSignatureExtractor._unparse(node.returns) if node.returns else None

        return FunctionSignature(
            name=func_name,
            params=params,
            return_type=return_type,
            docstring=docstring,
        )

    @staticmethod
    def _unparse(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        try:
            return ast.unparse(node).strip()
        except AttributeError:
            # Fallback for Python versions prior to 3.9 if unparse is missing
            if isinstance(node, ast.Name):
                return node.id
            elif isinstance(node, ast.Constant):
                return str(node.value)
            elif isinstance(node, ast.Subscript):
                return f"{ASTSignatureExtractor._unparse(node.value)}[{ASTSignatureExtractor._unparse(node.slice)}]"
            elif isinstance(node, ast.Attribute):
                return f"{ASTSignatureExtractor._unparse(node.value)}.{node.attr}"
            return str(node)


# ---------------------------------------------------------------------------
# Docstring Parser
# ---------------------------------------------------------------------------

class DocstringParser:
    """
    Parses Google-style and Sphinx/reST style docstrings into structured metadata.
    """

    @staticmethod
    def parse(docstring_text: str | None) -> ParsedDocstring:
        if not docstring_text or not docstring_text.strip():
            return ParsedDocstring()

        lines = [line.rstrip() for line in docstring_text.strip().splitlines()]
        summary = lines[0] if lines else ""

        parsed_params: dict[str, ParsedDocParam] = {}
        returns_type: str | None = None
        returns_desc: str | None = None

        current_section = None
        current_param_name = None

        # Regex patterns for Google-style sections
        google_args_pattern = re.compile(r"^\s*(?:Args|Parameters|Arguments)\s*:\s*$", re.IGNORECASE)
        google_returns_pattern = re.compile(r"^\s*(?:Returns|Yields|Return)\s*:\s*$", re.IGNORECASE)
        google_raises_pattern = re.compile(r"^\s*(?:Raises)\s*:\s*$", re.IGNORECASE)

        # Regex for Google-style param entry e.g. "param_name (int): Description" or "param_name: Description"
        google_param_re = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\(([^)]+)\))?\s*:\s*(.*)$")

        # Regex for Sphinx reST style e.g. ":param x: description" or ":type x: int" or ":returns: description" or ":rtype: int"
        sphinx_param_re = re.compile(r"^\s*:param\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$")
        sphinx_type_re = re.compile(r"^\s*:type\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$")
        sphinx_returns_re = re.compile(r"^\s*:returns?\s*:\s*(.*)$")
        sphinx_rtype_re = re.compile(r"^\s*:rtype\s*:\s*(.*)$")

        for line in lines[1:]:
            line_str = line.strip()
            if not line_str:
                continue

            # Section headers
            if google_args_pattern.match(line):
                current_section = "args"
                current_param_name = None
                continue
            elif google_returns_pattern.match(line):
                current_section = "returns"
                current_param_name = None
                continue
            elif google_raises_pattern.match(line):
                current_section = "raises"
                current_param_name = None
                continue

            # Check Sphinx style inline directives
            sph_p = sphinx_param_re.match(line)
            if sph_p:
                p_name, p_desc = sph_p.group(1), sph_p.group(2)
                if p_name not in parsed_params:
                    parsed_params[p_name] = ParsedDocParam(name=p_name, description=p_desc)
                else:
                    parsed_params[p_name].description = p_desc
                continue

            sph_t = sphinx_type_re.match(line)
            if sph_t:
                p_name, p_type = sph_t.group(1), sph_t.group(2)
                if p_name not in parsed_params:
                    parsed_params[p_name] = ParsedDocParam(name=p_name, type_desc=p_type)
                else:
                    parsed_params[p_name].type_desc = p_type
                continue

            sph_r = sphinx_returns_re.match(line)
            if sph_r:
                returns_desc = sph_r.group(1)
                continue

            sph_rt = sphinx_rtype_re.match(line)
            if sph_rt:
                returns_type = sph_rt.group(1)
                continue

            # Parse Google style entries
            if current_section == "args":
                param_match = google_param_re.match(line)
                if param_match:
                    p_name = param_match.group(1)
                    p_type = param_match.group(2)
                    p_desc = param_match.group(3)
                    parsed_params[p_name] = ParsedDocParam(
                        name=p_name, type_desc=p_type, description=p_desc
                    )
                    current_param_name = p_name
                elif current_param_name and current_param_name in parsed_params:
                    # Multi-line param description continuation
                    parsed_params[current_param_name].description += f" {line_str}"

            elif current_section == "returns":
                # Google style return line e.g. "dict: Return summary description" or "Return summary"
                ret_match = re.match(r"^\s*(?:([a-zA-Z0-9_\[\], .|]+)\s*:\s*)?(.*)$", line_str)
                if ret_match:
                    r_type = ret_match.group(1)
                    r_desc = ret_match.group(2)
                    if r_type and not returns_type:
                        returns_type = r_type
                    if r_desc:
                        returns_desc = f"{returns_desc} {r_desc}" if returns_desc else r_desc

        return ParsedDocstring(
            summary=summary,
            params=parsed_params,
            returns_type=returns_type,
            returns_desc=returns_desc,
        )


# ---------------------------------------------------------------------------
# Accuracy & Hallucination Auditor
# ---------------------------------------------------------------------------

class DocstringAccuracyAuditor:
    """
    Audits parsed docstring against actual FunctionSignature to detect hallucinations,
    missing parameters, type mismatches, default value contradictions, and return mismatches.
    """

    @staticmethod
    def audit(sig: FunctionSignature, parsed_doc: ParsedDocstring) -> DocstringAccuracyReport:
        discrepancies: list[DocstringDiscrepancy] = []

        code_params = {p.name: p for p in sig.params if p.name not in ("self", "cls")}
        doc_params = parsed_doc.params

        # 1. Hallucinated Parameters: In docstring, but NOT in code signature
        for doc_p_name in doc_params:
            if doc_p_name not in code_params and not doc_p_name.startswith("*"):
                discrepancies.append(
                    DocstringDiscrepancy(
                        discrepancy_type="HALLUCINATED_PARAM",
                        param_name=doc_p_name,
                        description=f"Docstring documents non-existent parameter '{doc_p_name}' (Hallucination).",
                        expected="Parameter not present in function signature",
                        actual=f"Documented as: {doc_params[doc_p_name].type_desc or 'no type'}",
                        severity="High",
                    )
                )

        # 2. Missing Parameters: In code signature, but missing from docstring
        for code_p_name, code_param in code_params.items():
            clean_name = code_p_name.lstrip("*")
            if clean_name not in doc_params and code_p_name not in doc_params:
                discrepancies.append(
                    DocstringDiscrepancy(
                        discrepancy_type="MISSING_PARAM",
                        param_name=code_p_name,
                        description=f"Function parameter '{code_p_name}' is missing from docstring documentation.",
                        expected=f"Documented parameter for {code_p_name} ({code_param.type_annotation or 'any'})",
                        actual="Missing from docstring Args section",
                        severity="Medium",
                    )
                )

        # 3. Type Annotation Mismatches & Default Value Contradictions
        for code_p_name, code_param in code_params.items():
            clean_name = code_p_name.lstrip("*")
            doc_p = doc_params.get(clean_name) or doc_params.get(code_p_name)
            if not doc_p:
                continue

            # Check Type Mismatch
            if code_param.type_annotation and doc_p.type_desc:
                c_type_norm = DocstringAccuracyAuditor._normalize_type(code_param.type_annotation)
                d_type_norm = DocstringAccuracyAuditor._normalize_type(doc_p.type_desc)

                if c_type_norm and d_type_norm and not DocstringAccuracyAuditor._types_compatible(c_type_norm, d_type_norm):
                    discrepancies.append(
                        DocstringDiscrepancy(
                            discrepancy_type="TYPE_MISMATCH",
                            param_name=code_p_name,
                            description=f"Type mismatch for parameter '{code_p_name}': Code type annotation '{code_param.type_annotation}' contradicts docstring '{doc_p.type_desc}'.",
                            expected=code_param.type_annotation,
                            actual=doc_p.type_desc,
                            severity="High",
                        )
                    )

            # Check Default Value Discrepancy in docstring description or type
            if code_param.default_value is not None and doc_p.description:
                # Look for "Defaults to X" or "default: X" in description
                def_match = re.search(r"defaults?\s*(?:to|=|\:)?\s*([^\.\,;\s]+)", doc_p.description, re.IGNORECASE)
                if def_match:
                    doc_def = def_match.group(1).strip()
                    code_def = str(code_param.default_value).strip()
                    if doc_def.lower() != code_def.lower() and doc_def.strip("'\"") != code_def.strip("'\""):
                        discrepancies.append(
                            DocstringDiscrepancy(
                                discrepancy_type="DEFAULT_VALUE_MISMATCH",
                                param_name=code_p_name,
                                description=f"Default value discrepancy for '{code_p_name}': Code default '{code_def}' conflicts with docstring default '{doc_def}'.",
                                expected=code_def,
                                actual=doc_def,
                                severity="Medium",
                            )
                        )

        # 4. Return Type Discrepancies
        if sig.return_type and parsed_doc.returns_type:
            c_ret_norm = DocstringAccuracyAuditor._normalize_type(sig.return_type)
            d_ret_norm = DocstringAccuracyAuditor._normalize_type(parsed_doc.returns_type)
            if c_ret_norm and d_ret_norm and not DocstringAccuracyAuditor._types_compatible(c_ret_norm, d_ret_norm):
                discrepancies.append(
                    DocstringDiscrepancy(
                        discrepancy_type="RETURN_TYPE_MISMATCH",
                        param_name="returns",
                        description=f"Return type mismatch: Function return annotation '{sig.return_type}' conflicts with docstring return type '{parsed_doc.returns_type}'.",
                        expected=sig.return_type,
                        actual=parsed_doc.returns_type,
                        severity="High",
                    )
                )

        # Score calculation: base 100 minus penalties
        penalties = 0
        hallucinations = 0
        for d in discrepancies:
            if d.discrepancy_type == "HALLUCINATED_PARAM":
                penalties += 25
                hallucinations += 1
            elif d.discrepancy_type == "TYPE_MISMATCH":
                penalties += 15
            elif d.discrepancy_type == "RETURN_TYPE_MISMATCH":
                penalties += 15
            elif d.discrepancy_type == "MISSING_PARAM":
                penalties += 10
            elif d.discrepancy_type == "DEFAULT_VALUE_MISMATCH":
                penalties += 10

        score = max(0, min(100, 100 - penalties))
        status = "PASS" if (score >= 85 and hallucinations == 0) else "FAIL"

        param_sigs = [f"{p.name}: {p.type_annotation or 'Any'}" for p in sig.params]
        sig_summary = f"{sig.name}({', '.join(param_sigs)}) -> {sig.return_type or 'Any'}"

        summary = (
            f"Audited docstring for '{sig.name}': {len(discrepancies)} discrepancy(s) found. "
            f"Docstring Accuracy Score: {score}/100 ({status})."
        )

        suggested_doc = None
        if discrepancies:
            suggested_doc = DocstringRefiner.generate_ground_truth_docstring(sig, parsed_doc)

        return DocstringAccuracyReport(
            status=status,
            score=score,
            summary=summary,
            function_name=sig.name,
            signature_summary=sig_summary,
            discrepancies=discrepancies,
            suggested_docstring=suggested_doc,
        )

    @staticmethod
    def _normalize_type(t_str: str) -> str:
        clean = t_str.strip().lower()
        clean = re.sub(r"\btyping\.", "", clean)
        clean = re.sub(r"\boptional\[(.*?)\]", r"\1", clean)
        clean = clean.replace(" ", "")
        return clean

    @staticmethod
    def _types_compatible(t1: str, t2: str) -> bool:
        if t1 == t2 or t1 in t2 or t2 in t1:
            return True
        # Type aliases & synonyms
        synonyms = {
            "str": {"string", "text", "str"},
            "int": {"integer", "int", "number"},
            "float": {"float", "number", "double"},
            "bool": {"boolean", "bool"},
            "dict": {"dictionary", "dict", "mapping", "json"},
            "list": {"array", "list", "sequence", "iterable"},
            "tuple": {"tuple", "pair"},
            "none": {"none", "nonetype", "null"},
        }
        for syn_set in synonyms.values():
            if t1 in syn_set and t2 in syn_set:
                return True
        return False


# ---------------------------------------------------------------------------
# Docstring Refiner (Ground-Truth Auto-Formatter)
# ---------------------------------------------------------------------------

class DocstringRefiner:
    """
    Generates 100% accurate, ground-truth Google-style docstrings from AST signatures.
    """

    @staticmethod
    def generate_ground_truth_docstring(
        sig: FunctionSignature, parsed_doc: ParsedDocstring | None = None
    ) -> str:
        summary_line = (
            parsed_doc.summary if (parsed_doc and parsed_doc.summary) else f"Performs {sig.name} operation."
        )

        lines = [f'"""', summary_line, ""]

        valid_params = [p for p in sig.params if p.name not in ("self", "cls")]
        if valid_params:
            lines.append("Args:")
            for p in valid_params:
                p_type = p.type_annotation or "Any"
                def_str = f" Defaults to {p.default_value}." if p.default_value is not None else ""

                # Preserve existing param description if available and non-hallucinated
                p_desc = f"Parameter {p.name}."
                if parsed_doc and p.name in parsed_doc.params:
                    existing_desc = parsed_doc.params[p.name].description
                    if existing_desc:
                        # strip duplicate defaults string if present
                        clean_desc = re.sub(r"defaults?\s*(?:to|=|\:)?\s*[^\.\,;\s]+", "", existing_desc, flags=re.IGNORECASE).strip()
                        if clean_desc:
                            p_desc = clean_desc

                lines.append(f"    {p.name} ({p_type}): {p_desc}{def_str}")
            lines.append("")

        if sig.return_type and sig.return_type != "None":
            lines.append("Returns:")
            r_desc = parsed_doc.returns_desc if (parsed_doc and parsed_doc.returns_desc) else "Return value."
            lines.append(f"    {sig.return_type}: {r_desc}")
            lines.append("")

        lines.append('"""')
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public Entry Points
# ---------------------------------------------------------------------------

def verify_function_docstring(func_code: str, docstring: str | None = None) -> dict[str, Any]:
    """
    Verifies the docstring of a single Python function code string.
    Returns AgentResponse-shaped dict with complete DocstringAccuracyReport details.
    """
    sig = ASTSignatureExtractor.extract_from_code(func_code)
    if not sig:
        return {
            "agent_name": "docstring_verifier",
            "summary": "Failed to parse function signature from code.",
            "details": {"error": "Invalid Python code or no function definition found"},
            "confidence": 0.0,
        }

    target_doc = docstring if docstring is not None else sig.docstring
    parsed_doc = DocstringParser.parse(target_doc)
    report = DocstringAccuracyAuditor.audit(sig, parsed_doc)

    return {
        "agent_name": "docstring_verifier",
        "summary": report.summary,
        "details": {
            "report": report.to_dict(),
            "markdown_report": report.to_markdown(),
            "function_name": sig.name,
        },
        "confidence": round(report.score / 100.0, 2),
    }


def verify_file_docstrings(filepath: str) -> dict[str, Any]:
    """
    Verifies docstrings for all functions in a Python source file.
    """
    if not os.path.exists(filepath):
        return {
            "agent_name": "docstring_verifier",
            "summary": f"File does not exist: {filepath}",
            "details": {"error": "File not found", "filepath": filepath},
            "confidence": None,
        }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
        tree = ast.parse(code, filename=filepath)
    except Exception as e:
        return {
            "agent_name": "docstring_verifier",
            "summary": f"Error parsing file {filepath}: {e}",
            "details": {"error": str(e), "filepath": filepath},
            "confidence": None,
        }

    reports: list[dict[str, Any]] = []
    total_score = 0
    passed_count = 0

    func_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not func_nodes:
        return {
            "agent_name": "docstring_verifier",
            "summary": f"No functions found in {os.path.basename(filepath)}.",
            "details": {"filepath": filepath, "function_count": 0},
            "confidence": 1.0,
        }

    for node in func_nodes:
        sig = ASTSignatureExtractor.extract_from_node(node)
        parsed_doc = DocstringParser.parse(sig.docstring)
        rep = DocstringAccuracyAuditor.audit(sig, parsed_doc)

        reports.append(rep.to_dict())
        total_score += rep.score
        if rep.status == "PASS":
            passed_count += 1

    avg_score = round(total_score / len(func_nodes))
    overall_status = "PASS" if passed_count == len(func_nodes) else "FAIL"
    summary = f"Audited {len(func_nodes)} function(s) in '{os.path.basename(filepath)}': {passed_count}/{len(func_nodes)} passed ({avg_score}/100)."

    return {
        "agent_name": "docstring_verifier",
        "summary": summary,
        "details": {
            "overall_status": overall_status,
            "average_score": avg_score,
            "passed_functions": passed_count,
            "total_functions": len(func_nodes),
            "reports": reports,
            "filepath": filepath,
        },
        "confidence": round(avg_score / 100.0, 2),
    }


def audit_and_fix_docstring(func_code: str, docstring: str | None = None) -> dict[str, Any]:
    """
    Audits a function docstring for accuracy and returns the corrected ground-truth docstring if inaccurate.
    """
    res = verify_function_docstring(func_code, docstring)
    rep_dict = res.get("details", {}).get("report", {})
    if rep_dict.get("status") == "FAIL":
        sig = ASTSignatureExtractor.extract_from_code(func_code)
        parsed_doc = DocstringParser.parse(docstring or (sig.docstring if sig else None))
        if sig:
            corrected_doc = DocstringRefiner.generate_ground_truth_docstring(sig, parsed_doc)
            res["details"]["corrected_docstring"] = corrected_doc
            res["summary"] += " Generated 100% ground-truth corrected docstring."

    return res


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    res = verify_file_docstrings(target)
    print(res["summary"])
