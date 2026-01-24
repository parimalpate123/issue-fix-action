"""
GitHub API Client for Issue Agent
"""

import os
import logging
from typing import Dict, Any, Optional, List
from github import Github
from github.GithubException import GithubException

logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for GitHub API operations"""
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize GitHub client
        
        Args:
            token: GitHub personal access token (or use GITHUB_TOKEN env var)
        """
        self.token = token or os.environ.get('GITHUB_TOKEN')
        if not self.token:
            raise ValueError("GitHub token required. Set GITHUB_TOKEN environment variable.")
        
        self.github = Github(self.token)
        logger.info("GitHub client initialized")
    
    def get_issue(self, repo_full_name: str, issue_number: int) -> Dict[str, Any]:
        """
        Get issue details
        
        Args:
            repo_full_name: Repository name (org/repo)
            issue_number: Issue number
            
        Returns:
            Issue data dictionary
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            
            return {
                'number': issue.number,
                'title': issue.title,
                'body': issue.body,
                'state': issue.state,
                'labels': [label.name for label in issue.labels],
                'user': issue.user.login,
                'created_at': issue.created_at.isoformat(),
                'html_url': issue.html_url
            }
        except GithubException as e:
            logger.error(f"Failed to get issue {issue_number} from {repo_full_name}: {e}")
            raise
    
    def get_repo_files(self, repo_full_name: str, path: str = '', ref: str = 'main') -> List[Dict[str, Any]]:
        """
        Get repository file structure
        
        Args:
            repo_full_name: Repository name (org/repo)
            path: Path to directory (empty for root)
            ref: Branch or commit SHA (default: 'main')
            
        Returns:
            List of file/directory info
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            contents = repo.get_contents(path, ref=ref)
            
            if not isinstance(contents, list):
                contents = [contents]
            
            files = []
            for item in contents:
                files.append({
                    'name': item.name,
                    'path': item.path,
                    'type': item.type,  # 'file' or 'dir'
                    'size': item.size if item.type == 'file' else 0,
                    'sha': item.sha,
                    'url': item.html_url
                })
            
            return files
        except GithubException as e:
            logger.error(f"Failed to get files from {repo_full_name}/{path}: {e}")
            raise
    
    def get_file_content(self, repo_full_name: str, file_path: str, ref: str = 'main') -> str:
        """
        Get file content
        
        Args:
            repo_full_name: Repository name (org/repo)
            file_path: Path to file
            ref: Branch or commit SHA
            
        Returns:
            File content as string
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            file = repo.get_contents(file_path, ref=ref)
            
            if file.encoding == 'base64':
                import base64
                return base64.b64decode(file.content).decode('utf-8')
            return file.content
        except GithubException as e:
            logger.error(f"Failed to get file {file_path} from {repo_full_name}: {e}")
            raise
    
    def create_branch(self, repo_full_name: str, branch_name: str, base_branch: str = 'main') -> bool:
        """
        Create a new branch
        
        Args:
            repo_full_name: Repository name (org/repo)
            branch_name: Name of new branch
            base_branch: Base branch to branch from
            
        Returns:
            True if successful
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            base_ref = repo.get_git_ref(f'heads/{base_branch}')
            repo.create_git_ref(ref=f'refs/heads/{branch_name}', sha=base_ref.object.sha)
            logger.info(f"Created branch {branch_name} from {base_branch}")
            return True
        except GithubException as e:
            logger.error(f"Failed to create branch {branch_name}: {e}")
            raise
    
    def create_or_update_file(
        self,
        repo_full_name: str,
        file_path: str,
        content: str,
        branch: str,
        message: str,
        sha: Optional[str] = None
    ) -> bool:
        """
        Create or update a file
        
        Args:
            repo_full_name: Repository name (org/repo)
            file_path: Path to file
            content: File content
            branch: Branch name
            message: Commit message
            sha: SHA of existing file (for updates)
            
        Returns:
            True if successful
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            
            if sha:
                # Update existing file
                repo.update_file(
                    path=file_path,
                    message=message,
                    content=content,
                    sha=sha,
                    branch=branch
                )
            else:
                # Create new file
                repo.create_file(
                    path=file_path,
                    message=message,
                    content=content,
                    branch=branch
                )
            
            logger.info(f"Updated file {file_path} in branch {branch}")
            return True
        except GithubException as e:
            logger.error(f"Failed to create/update file {file_path}: {e}")
            raise
    
    def create_pull_request(
        self,
        repo_full_name: str,
        title: str,
        body: str,
        head: str,
        base: str = 'main'
    ) -> Dict[str, Any]:
        """
        Create a pull request
        
        Args:
            repo_full_name: Repository name (org/repo)
            title: PR title
            body: PR body
            head: Head branch (with fix)
            base: Base branch (usually main)
            
        Returns:
            PR data dictionary
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base
            )
            
            logger.info(f"Created PR #{pr.number}: {pr.html_url}")
            
            return {
                'number': pr.number,
                'title': pr.title,
                'html_url': pr.html_url,
                'state': pr.state
            }
        except GithubException as e:
            logger.error(f"Failed to create PR in {repo_full_name}: {e}")
            raise
    
    def add_issue_comment(self, repo_full_name: str, issue_number: int, comment: str) -> bool:
        """
        Add comment to issue
        
        Args:
            repo_full_name: Repository name (org/repo)
            issue_number: Issue number
            comment: Comment text
            
        Returns:
            True if successful
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            issue.create_comment(comment)
            logger.info(f"Added comment to issue #{issue_number}")
            return True
        except GithubException as e:
            logger.error(f"Failed to add comment to issue {issue_number}: {e}")
            raise
