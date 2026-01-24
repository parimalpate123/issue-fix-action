#!/usr/bin/env python3
"""
Standalone PR Creator Script
Creates PR from previously generated fix
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
from src.agents.pr_creator import PRCreator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Create PR from fix result')
    parser.add_argument('--issue-number', type=int, required=True, help='GitHub issue number')
    parser.add_argument('--repo', type=str, required=True, help='Repository name (org/repo)')
    parser.add_argument('--fix-dir', type=str, required=True, help='Directory containing fix_result.json')
    
    args = parser.parse_args()
    
    # Load fix result
    fix_dir = Path(args.fix_dir)
    fix_result_path = fix_dir / 'fix_result.json'
    
    if not fix_result_path.exists():
        logger.error(f"Fix result not found: {fix_result_path}")
        sys.exit(1)
    
    with open(fix_result_path, 'r') as f:
        fix_result = json.load(f)
    
    # Initialize clients
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        logger.error("GITHUB_TOKEN environment variable not set")
        sys.exit(1)
    
    github_client = GitHubClient(github_token)
    pr_creator = PRCreator(github_client)
    
    # Create PR
    pr_result = pr_creator.create_pr_with_fix(
        args.repo,
        args.issue_number,
        fix_result
    )
    
    if pr_result.get('success'):
        logger.info(f"✅ PR created: {pr_result.get('pr_url')}")
    else:
        logger.error(f"PR creation failed: {pr_result.get('error')}")
        sys.exit(1)


if __name__ == '__main__':
    main()
