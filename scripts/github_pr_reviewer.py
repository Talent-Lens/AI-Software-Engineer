"""
Standalone GitHub PR AI Reviewer CLI (TASK-FS4)
Can be invoked in CI/CD pipelines or locally to analyze PR diffs and post comments.

Usage:
    python scripts/github_pr_reviewer.py --repo owner/repo --pr 42
    python scripts/github_pr_reviewer.py --files src/auth.py,src/db.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import logging
from typing import List

# Add workspace root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.services.github_service import (
    fetch_pr_files,
    format_ai_pr_review,
    post_github_pr_comment,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ai_pr_reviewer")


async def run_review_cli(
    repo_full_name: str,
    pr_number: int,
    files_list: List[str],
    token: str = None,
    post_comment: bool = True,
):
    owner, repo = repo_full_name.split("/") if "/" in repo_full_name else ("", repo_full_name)
    logger.info("Starting AI Review for %s PR #%d...", repo_full_name, pr_number)

    analysis_results = []
    from graph import run_pipeline

    targets = files_list
    if not targets and owner and repo and pr_number:
        logger.info("Fetching modified files from GitHub API...")
        pr_files = await fetch_pr_files(owner, repo, pr_number, token=token)
        targets = [f.get("filename") for f in pr_files if f.get("filename", "").endswith((".py", ".js", ".ts", ".go", ".java"))]

    if not targets:
        logger.info("No specific target files found; running pipeline on graph.py baseline.")
        targets = ["graph.py"]

    for file_path in targets:
        if os.path.exists(file_path) or file_path == "graph.py":
            logger.info("Analyzing %s...", file_path)
            try:
                res = run_pipeline(file_path)
                analysis_results.append({
                    "filepath": file_path,
                    "agent_response": res.get("agent_response", {}),
                    "review": res.get("review", {}),
                    "security_response": res.get("security_response", {}),
                })
            except Exception as err:
                logger.error("Error analyzing %s: %s", file_path, err)

    # Format Markdown Review
    markdown_review = format_ai_pr_review(pr_number, repo_full_name, analysis_results)
    print("\n" + "=" * 60)
    print("AI REVIEW OUTPUT:")
    print("=" * 60)
    print(markdown_review)
    print("=" * 60 + "\n")

    if post_comment and owner and repo and pr_number:
        logger.info("Posting AI review comment to GitHub PR #%d...", pr_number)
        posted = await post_github_pr_comment(owner, repo, pr_number, markdown_review, token=token)
        if posted:
            logger.info("Review comment successfully posted on GitHub PR!")
        else:
            logger.warning("Could not post comment on GitHub (check GITHUB_TOKEN permissions).")

    return markdown_review


def main():
    parser = argparse.ArgumentParser(description="AI Software Engineer GitHub PR Reviewer")
    parser.add_argument("--repo", type=str, default="Talent-Lens/AI-Software-Engineer", help="GitHub Repository (owner/repo)")
    parser.add_argument("--pr", type=int, default=1, help="Pull Request Number")
    parser.add_argument("--files", type=str, default="", help="Comma-separated list of modified files")
    parser.add_argument("--token", type=str, default=os.getenv("GITHUB_TOKEN"), help="GitHub Token")
    parser.add_argument("--no-post", action="store_true", help="Do not post comment to GitHub, only print to stdout")

    args = parser.parse_args()
    files_list = [f.strip() for f in args.files.split(",") if f.strip()]

    asyncio.run(
        run_review_cli(
            repo_full_name=args.repo,
            pr_number=args.pr,
            files_list=files_list,
            token=args.token,
            post_comment=not args.no_post,
        )
    )


if __name__ == "__main__":
    main()
