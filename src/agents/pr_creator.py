"""
PR Creator
Creates Pull Requests with generated fixes
"""

import logging
import os
from typing import Dict, Any, List
from ..utils.github_client import GitHubClient

logger = logging.getLogger(__name__)


class PRCreator:
    """Creates Pull Requests with code fixes"""
    
    def __init__(self, github_client: GitHubClient):
        """
        Initialize PR Creator
        
        Args:
            github_client: GitHub API client
        """
        self.github_client = github_client
    
    def create_pr_with_fix(
        self,
        repo_full_name: str,
        issue_number: int,
        fix_result: Dict[str, Any],
        branch_prefix: str = 'fix/issue'
    ) -> Dict[str, Any]:
        """
        Create a PR with the generated fix
        
        Args:
            repo_full_name: Repository name (org/repo)
            issue_number: Issue number
            fix_result: Fix generation result
            branch_prefix: Prefix for branch name
            
        Returns:
            PR creation result
        """
        logger.info(f"Creating PR for issue #{issue_number}")
        
        analysis = fix_result.get('analysis', {})
        issue = analysis.get('issue', {})
        
        # Create branch name
        branch_name = f"{branch_prefix}-{issue_number}"
        
        try:
            # Create branch (force delete if exists from previous run)
            self.github_client.create_branch(repo_full_name, branch_name, force=True)
            
            # Apply file changes
            files_modified = []
            files_created = []
            
            # Group changes by file path to avoid multiple updates to same file
            files_to_update = {}
            for file_change in fix_result.get('files_to_modify', []):
                file_path = file_change.get('path')
                if not file_path:
                    continue
                
                # Collect all changes for this file
                if file_path not in files_to_update:
                    files_to_update[file_path] = []
                files_to_update[file_path].extend(file_change.get('changes', []))
            
            # Modify existing files (one update per file)
            for file_path, changes in files_to_update.items():
                # Get current file SHA - try branch first, then main
                sha = None
                try:
                    # Try to get SHA from the branch we're working on
                    repo_files = self.github_client.get_repo_files(repo_full_name, os.path.dirname(file_path) or '.', ref=branch_name)
                    current_file = next((f for f in repo_files if f['path'] == file_path), None)
                    if current_file:
                        sha = current_file.get('sha')
                except:
                    pass
                
                # If not found in branch, try main
                if not sha:
                    try:
                        repo_files = self.github_client.get_repo_files(repo_full_name, os.path.dirname(file_path) or '.', ref='main')
                        current_file = next((f for f in repo_files if f['path'] == file_path), None)
                        if current_file:
                            sha = current_file.get('sha')
                    except:
                        sha = None
                
                # Use the last change's new_code (or combine if needed)
                # For now, use the last change
                last_change = changes[-1] if changes else {}
                new_content = last_change.get('new_code', '')
                
                if new_content:
                    # Combine explanations if multiple changes
                    explanations = [c.get('explanation', '') for c in changes if c.get('explanation')]
                    commit_message = f"Fix: {', '.join(explanations) if explanations else 'Apply fix'}"
                    
                    self.github_client.create_or_update_file(
                        repo_full_name,
                        file_path,
                        new_content,
                        branch_name,
                        commit_message,
                        sha
                    )
                    files_modified.append(file_path)
            
            # Create new files
            for file_create in fix_result.get('files_to_create', []):
                file_path = file_create.get('path')
                content = file_create.get('content', '')
                if file_path and content:
                    commit_message = f"Add: {file_create.get('explanation', 'New file')}"
                    self.github_client.create_or_update_file(
                        repo_full_name,
                        file_path,
                        content,
                        branch_name,
                        commit_message
                    )
                    files_created.append(file_path)
            
            # Create PR
            pr_title = f"Fix: {issue.get('title', f'Issue #{issue_number}')}"
            pr_body = self._build_pr_body(issue, analysis, fix_result, files_modified, files_created)
            
            pr = self.github_client.create_pull_request(
                repo_full_name,
                pr_title,
                pr_body,
                branch_name,
                'main'
            )
            
            # Add comment to issue
            comment = f"✅ **Fix Generated and PR Created**\n\n"
            comment += f"PR: #{pr['number']} - {pr['html_url']}\n\n"
            comment += f"**Files Modified:** {len(files_modified)}\n"
            comment += f"**Files Created:** {len(files_created)}\n\n"
            comment += "The PR Review Agent will automatically review this PR."
            
            self.github_client.add_issue_comment(repo_full_name, issue_number, comment)
            
            logger.info(f"PR created successfully: {pr['html_url']}")
            
            return {
                'success': True,
                'pr_number': pr['number'],
                'pr_url': pr['html_url'],
                'branch': branch_name,
                'files_modified': files_modified,
                'files_created': files_created
            }
            
        except Exception as e:
            logger.error(f"Failed to create PR: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _build_pr_body(
        self,
        issue: Dict[str, Any],
        analysis: Dict[str, Any],
        fix_result: Dict[str, Any],
        files_modified: List[str],
        files_created: List[str]
    ) -> str:
        """Build PR description"""
        body = f"""## Fix for Issue #{issue.get('number')}

**Related Issue:** #{issue.get('number')} - {issue.get('html_url')}

### Root Cause
{analysis.get('root_cause', 'Unknown')}

### Fix Summary
{fix_result.get('summary', 'Code fix applied')}

### Changes Made

**Files Modified:**
{chr(10).join(f'- {f}' for f in files_modified) if files_modified else '- None'}

**Files Created:**
{chr(10).join(f'- {f}' for f in files_created) if files_created else '- None'}

### Testing Notes
{fix_result.get('testing_notes', 'Please test the fix manually')}

### Confidence
{fix_result.get('confidence', 0)}%

---
*This PR was automatically generated by the Issue Agent*
"""
        return body
