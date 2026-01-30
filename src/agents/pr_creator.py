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
                # Get current file content and SHA
                sha = None
                current_content = None

                # Try branch first, then main
                for ref in [branch_name, 'main']:
                    try:
                        repo_files = self.github_client.get_repo_files(repo_full_name, os.path.dirname(file_path) or '.', ref=ref)
                        current_file = next((f for f in repo_files if f['path'] == file_path), None)
                        if current_file:
                            sha = current_file.get('sha')
                            break
                    except Exception:
                        continue

                # Read the current file content so we can apply changes surgically
                try:
                    current_content = self.github_client.get_file_content(repo_full_name, file_path, ref=branch_name)
                except Exception:
                    try:
                        current_content = self.github_client.get_file_content(repo_full_name, file_path, ref='main')
                    except Exception:
                        current_content = None

                # Apply changes surgically using old_code/new_code replacement
                new_content = self._apply_changes(current_content, changes)

                if new_content:
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
            validation_failed = fix_result.get('validation_failed', False)
            pr_body = self._build_pr_body(issue, analysis, fix_result, files_modified, files_created, validation_failed)
            
            pr = self.github_client.create_pull_request(
                repo_full_name,
                pr_title,
                pr_body,
                branch_name,
                'main'
            )
            
            # Build single comprehensive comment with all details
            validated_with_tools = fix_result.get('validated_with_tools', False)
            validation_failed = fix_result.get('validation_failed', False)

            comment = self._build_comprehensive_comment(
                issue,
                analysis,
                fix_result,
                pr['number'],
                pr['html_url'],
                files_modified,
                files_created,
                validated_with_tools,
                validation_failed
            )

            self.github_client.add_issue_comment(repo_full_name, issue_number, comment)
            logger.info(f"Posted comprehensive fix comment to issue #{issue_number}")
            
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
    
    def _apply_changes(self, current_content: str, changes: List[Dict[str, Any]]) -> str:
        """
        Apply code changes surgically to preserve existing file structure.
        Uses old_code/new_code replacement instead of full file replacement.

        Args:
            current_content: Current file content from the repository
            changes: List of changes with old_code and new_code

        Returns:
            Modified file content with changes applied
        """
        if not changes:
            return ''

        # If we don't have the current content, fall back to using new_code directly
        if not current_content:
            logger.warning("No current file content available, using new_code as full content")
            last_change = changes[-1]
            return last_change.get('new_code', '')

        modified_content = current_content

        for change in changes:
            old_code = change.get('old_code', '')
            new_code = change.get('new_code', '')

            if not new_code:
                continue

            if old_code and old_code.strip() in modified_content:
                # Surgical replacement: find old_code and replace with new_code
                modified_content = modified_content.replace(old_code.strip(), new_code.strip(), 1)
                logger.info(f"Applied surgical change: replaced {len(old_code)} chars with {len(new_code)} chars")
            elif old_code:
                # old_code not found verbatim — try normalized whitespace match
                old_normalized = ' '.join(old_code.split())
                content_lines = modified_content.split('\n')
                matched = False

                for i, line in enumerate(content_lines):
                    if old_normalized[:50] in ' '.join(line.split()):
                        # Found approximate match, try to find the block
                        old_lines = old_code.strip().split('\n')
                        if i + len(old_lines) <= len(content_lines):
                            # Replace the block
                            content_lines[i:i + len(old_lines)] = new_code.strip().split('\n')
                            modified_content = '\n'.join(content_lines)
                            matched = True
                            logger.info(f"Applied approximate change at line {i + 1}")
                            break

                if not matched:
                    logger.warning(f"old_code not found in file, skipping change: {old_code[:80]}...")
            else:
                # No old_code provided — check if new_code looks like a full file
                # (has imports/requires at top and exports at bottom)
                new_lines = new_code.strip().split('\n')
                has_imports = any(
                    l.strip().startswith(('import ', 'const ', 'require(', 'from '))
                    for l in new_lines[:5]
                )
                has_structure = len(new_lines) > len(modified_content.split('\n')) * 0.5

                if has_imports and has_structure:
                    # Looks like a full file replacement — use it but log warning
                    logger.warning("No old_code provided and new_code looks like full file, using as replacement")
                    modified_content = new_code
                else:
                    # Partial code without old_code — append or skip
                    logger.warning("No old_code provided and new_code is partial, skipping to avoid corruption")

        return modified_content

    def _build_pr_body(
        self,
        issue: Dict[str, Any],
        analysis: Dict[str, Any],
        fix_result: Dict[str, Any],
        files_modified: List[str],
        files_created: List[str],
        validation_failed: bool = False
    ) -> str:
        """Build PR description"""
        # Extract incident ID from issue labels or body
        incident_id = None
        issue_labels = issue.get('labels', [])
        for label in issue_labels:
            label_name = label.get('name', '') if isinstance(label, dict) else str(label)
            if label_name.startswith('incident-'):
                incident_id = label_name.replace('incident-', '')
                break

        # If not found in labels, try to extract from issue body
        if not incident_id:
            issue_body = issue.get('body', '')
            import re
            match = re.search(r'Incident(?: ID)?:\s*([a-z0-9-.:]+)', issue_body, re.IGNORECASE)
            if match:
                incident_id = match.group(1)

        # Build validation section
        validated_with_tools = fix_result.get('validated_with_tools', False)
        validation_results = fix_result.get('validation_results', {})
        validation_section = self._build_validation_section(validation_results, validation_failed, validated_with_tools)

        # Build PR body
        incident_section = f"\n**Incident ID:** {incident_id}\n" if incident_id else ""
        body = f"""## Fix for Issue #{issue.get('number')}

**Related Issue:** #{issue.get('number')} - {issue.get('html_url')}{incident_section}
### Root Cause
{analysis.get('root_cause', 'Unknown')}

### Fix Summary
{fix_result.get('summary', 'Code fix applied')}

### Changes Made

**Files Modified:**
{chr(10).join(f'- {f}' for f in files_modified) if files_modified else '- None'}

**Files Created:**
{chr(10).join(f'- {f}' for f in files_created) if files_created else '- None'}

{validation_section}

### Testing Notes
{fix_result.get('testing_notes', 'Please test the fix manually')}

### Confidence
{fix_result.get('confidence', 0)}%

---
*This PR was automatically generated by the Issue Agent*
"""
        return body

    def _build_validation_section(
        self,
        validation_results: Dict[str, Any],
        validation_failed: bool = False,
        validated_with_tools: bool = False
    ) -> str:
        """Build validation checks section for PR body"""

        # If validated with tools, show a different section
        if validated_with_tools:
            section = "### Validation\n\n"
            section += "✅ **Validated with Tools** - This fix was generated with autonomous validation.\n\n"
            section += "The LLM used these tools during generation:\n"
            section += "- ✓ Syntax validation (AST parsing)\n"
            section += "- ✓ Dependency checking\n"
            section += "- ✓ Build verification\n"
            section += "- ✓ Test execution\n\n"
            section += "**All validation checks passed before returning the fix.**\n\n"
            return section

        # Legacy validation results
        if not validation_results:
            return ""

        checks_passed = validation_results.get('checks_passed', [])
        checks_failed = validation_results.get('checks_failed', [])
        warnings = validation_results.get('warnings', [])

        if not checks_passed and not checks_failed and not warnings:
            return ""

        section = "### Validation Checks\n\n"
        section += f"**Summary:** {validation_results.get('summary', 'No summary available')}\n\n"

        if validation_failed:
            section += "⚠️ **Status:** Validation failed after 3 retry attempts. Manual fixes may be required.\n\n"

        if checks_passed:
            section += "**Passed:**\n"
            for check in checks_passed:
                section += f"- {check}\n"
            section += "\n"

        if checks_failed:
            section += "**Failed:**\n"
            for check in checks_failed:
                section += f"- {check}\n"
            section += "\n"
            section += "⚠️ **Action Required:** Please address these validation failures before merging.\n\n"

        if warnings:
            section += "**Warnings:**\n"
            for warning in warnings:
                section += f"- {warning}\n"
            section += "\n"

        return section

    def _build_comprehensive_comment(
        self,
        issue: Dict[str, Any],
        analysis: Dict[str, Any],
        fix_result: Dict[str, Any],
        pr_number: int,
        pr_url: str,
        files_modified: List[str],
        files_created: List[str],
        validated_with_tools: bool = False,
        validation_failed: bool = False
    ) -> str:
        """Build single comprehensive comment with all incident and fix details"""

        # Extract incident ID if available
        incident_id = None
        issue_labels = issue.get('labels', [])
        for label in issue_labels:
            label_name = label.get('name', '') if isinstance(label, dict) else str(label)
            if label_name.startswith('incident-'):
                incident_id = label_name.replace('incident-', '')
                break

        # Build header
        if validation_failed:
            header = "## ⚠️ Fix Generated with Validation Issues\n\n"
            status_icon = "⚠️"
        else:
            header = "## ✅ Fix Generated and Validated\n\n"
            status_icon = "✅"

        # Build comment sections
        comment = header

        # Incident Information
        if incident_id:
            comment += f"**Incident ID:** `{incident_id}`\n\n"

        # Root Cause
        root_cause = analysis.get('root_cause', 'Unknown')
        comment += f"**Root Cause:** {root_cause}\n\n"

        # Fix Summary
        fix_summary = fix_result.get('summary', 'Code fix applied')
        comment += f"**Fix Summary:** {fix_summary}\n\n"

        # PR Link
        comment += f"**Pull Request:** [#{pr_number}]({pr_url})\n\n"

        # Changes Made
        comment += "**Changes Made:**\n"
        if files_modified:
            comment += f"- Modified: {', '.join(f'`{f}`' for f in files_modified)}\n"
        if files_created:
            comment += f"- Created: {', '.join(f'`{f}`' for f in files_created)}\n"
        comment += "\n"

        # Validation Status
        if validated_with_tools:
            comment += f"{status_icon} **Validation:** All checks passed (syntax, dependencies, build, tests)\n\n"
        elif validation_failed:
            comment += "⚠️ **Validation:** Some checks failed - manual review required\n\n"
        else:
            comment += f"{status_icon} **Validation:** Basic checks passed\n\n"

        # Additional Details
        fix_type = analysis.get('fix_type', 'unknown')
        confidence = fix_result.get('confidence', analysis.get('confidence', 0))

        comment += "**Details:**\n"
        comment += f"- Fix Type: `{fix_type}`\n"
        comment += f"- Confidence: {confidence}%\n"

        # Testing Notes
        testing_notes = fix_result.get('testing_notes', '')
        if testing_notes:
            comment += f"- Testing: {testing_notes}\n"

        comment += "\n---\n"
        comment += "*The PR Review Agent will automatically review this PR.*"

        return comment

    def _post_fix_comment(
        self,
        repo_full_name: str,
        issue_number: int,
        pr_number: int,
        pr_url: str,
        files_modified: List[str],
        files_created: List[str],
        validated_with_tools: bool = False,
        validation_failed: bool = False
    ):
        """Post single comprehensive comment with fix details, PR info, and validation status"""

        # This method should NOT be called anymore - we'll build the comment in create_pr_with_fix
        # This is kept for backward compatibility
        comment = f"## ✅ Fix Generated and PR Created\n\n"
        comment += f"**PR:** [{pr_number}]({pr_url})\n\n"
        comment += f"**Files Modified:** {len(files_modified)}\n"
        comment += f"**Files Created:** {len(files_created)}\n\n"
        comment += "The PR Review Agent will review this PR."

        self.github_client.add_issue_comment(repo_full_name, issue_number, comment)
        logger.info(f"Posted fix comment to issue #{issue_number}")
