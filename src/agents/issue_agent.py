#!/usr/bin/env python3
"""
Main Issue Agent Script
Orchestrates issue analysis, fix generation, and PR creation
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.llm.bedrock import BedrockClient
from src.utils.github_client import GitHubClient
from src.agents.issue_analyzer import IssueAnalyzer
from src.agents.fix_generator import FixGenerator
from src.agents.pr_creator import PRCreator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Issue Agent - Analyze issues and generate fixes')
    parser.add_argument('--issue-number', type=int, required=True, help='GitHub issue number')
    parser.add_argument('--repo', type=str, required=True, help='Repository name (org/repo)')
    parser.add_argument('--output-dir', type=str, default='./agent-output', help='Output directory')
    parser.add_argument('--skip-pr', action='store_true', help='Skip PR creation (only generate fix)')
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize clients
    logger.info("Initializing clients...")
    
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        logger.error("GITHUB_TOKEN environment variable not set")
        sys.exit(1)
    
    github_client = GitHubClient(github_token)
    
    bedrock_model = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20240620-v1:0')
    bedrock_region = os.environ.get('AWS_REGION', 'us-east-1')
    bedrock_client = BedrockClient(region=bedrock_region, model_id=bedrock_model)
    
    # Initialize agents
    issue_analyzer = IssueAnalyzer(github_client, bedrock_client)
    fix_generator = FixGenerator(github_client, bedrock_client)
    pr_creator = PRCreator(github_client)
    
    try:
        # Step 1: Analyze issue
        logger.info(f"Step 1: Analyzing issue #{args.issue_number}...")
        analysis = issue_analyzer.analyze_issue(args.repo, args.issue_number)
        
        # Save analysis
        with open(output_dir / 'analysis.json', 'w') as f:
            json.dump(analysis, f, indent=2)
        logger.info(f"Analysis saved to {output_dir / 'analysis.json'}")
        
        # Step 2: Generate fix
        logger.info("Step 2: Generating fix...")
        fix_result = fix_generator.generate_fix(args.repo, analysis)
        
        # Save fix result
        with open(output_dir / 'fix_result.json', 'w') as f:
            json.dump(fix_result, f, indent=2)
        logger.info(f"Fix result saved to {output_dir / 'fix_result.json'}")
        
        if not fix_result.get('success'):
            logger.error(f"Fix generation failed: {fix_result.get('error')}")
            sys.exit(1)
        
        # Step 3: Create PR (if not skipped)
        if not args.skip_pr:
            logger.info("Step 3: Creating PR...")
            pr_result = pr_creator.create_pr_with_fix(
                args.repo,
                args.issue_number,
                fix_result
            )
            
            # Save PR result
            with open(output_dir / 'pr_result.json', 'w') as f:
                json.dump(pr_result, f, indent=2)
            logger.info(f"PR result saved to {output_dir / 'pr_result.json'}")
            
            if pr_result.get('success'):
                logger.info(f"✅ PR created successfully: {pr_result.get('pr_url')}")
            else:
                logger.error(f"PR creation failed: {pr_result.get('error')}")
                sys.exit(1)
        else:
            logger.info("PR creation skipped (--skip-pr)")
        
        logger.info("✅ Issue Agent completed successfully")
        
    except Exception as e:
        logger.error(f"Issue Agent failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
