#!/usr/bin/env python3
"""
Update Issue Comment Script
Adds status comment to issue
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.github_client import GitHubClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Update issue comment with status')
    parser.add_argument('--issue-number', type=int, required=True, help='GitHub issue number')
    parser.add_argument('--repo', type=str, required=True, help='Repository name (org/repo)')
    parser.add_argument('--status-dir', type=str, required=True, help='Directory containing status files')
    
    args = parser.parse_args()
    
    # Load status files
    status_dir = Path(args.status_dir)
    
    status_comment = "## Issue Agent Status\n\n"
    
    # Check for analysis
    if (status_dir / 'analysis.json').exists():
        with open(status_dir / 'analysis.json', 'r') as f:
            analysis = json.load(f)
        status_comment += f"✅ **Analysis Complete**\n"
        status_comment += f"- Root Cause: {analysis.get('root_cause', 'Unknown')}\n"
        status_comment += f"- Fix Type: {analysis.get('fix_type', 'unknown')}\n"
        status_comment += f"- Confidence: {analysis.get('confidence', 0)}%\n\n"
    
    # Check for fix result
    if (status_dir / 'fix_result.json').exists():
        with open(status_dir / 'fix_result.json', 'r') as f:
            fix_result = json.load(f)
        if fix_result.get('success'):
            status_comment += f"✅ **Fix Generated**\n"
            status_comment += f"- Files to modify: {len(fix_result.get('files_to_modify', []))}\n"
            status_comment += f"- Files to create: {len(fix_result.get('files_to_create', []))}\n\n"
        else:
            status_comment += f"❌ **Fix Generation Failed**\n"
            status_comment += f"- Error: {fix_result.get('error', 'Unknown')}\n\n"
    
    # Check for PR result
    if (status_dir / 'pr_result.json').exists():
        with open(status_dir / 'pr_result.json', 'r') as f:
            pr_result = json.load(f)
        if pr_result.get('success'):
            status_comment += f"✅ **PR Created**\n"
            status_comment += f"- PR: #{pr_result.get('pr_number')} - {pr_result.get('pr_url')}\n\n"
        else:
            status_comment += f"❌ **PR Creation Failed**\n"
            status_comment += f"- Error: {pr_result.get('error', 'Unknown')}\n\n"
    
    # Initialize GitHub client
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        logger.error("GITHUB_TOKEN environment variable not set")
        sys.exit(1)
    
    github_client = GitHubClient(github_token)
    
    # Add comment
    github_client.add_issue_comment(args.repo, args.issue_number, status_comment)
    logger.info("Status comment added to issue")


if __name__ == '__main__':
    main()
