"""
Build Runner
Runs code build/compilation in a sandbox
"""

import subprocess
import tempfile
import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class BuildRunner:
    """Runs build in a temporary directory sandbox"""

    def build(self, files: Dict[str, str], build_command: str = None) -> Dict[str, Any]:
        """
        Build code in a temporary directory sandbox

        Args:
            files: Map of file paths to contents
            build_command: Optional build command. Auto-detected if not provided.

        Returns:
            Build result with success status and output
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # Write files to temp directory
                for file_path, content in files.items():
                    full_path = os.path.join(tmpdir, file_path)
                    os.makedirs(os.path.dirname(full_path) or tmpdir, exist_ok=True)
                    with open(full_path, 'w') as f:
                        f.write(content)

                # Auto-detect build command if not provided
                if not build_command:
                    build_command = self._detect_build_command(files)

                if not build_command:
                    return {
                        "success": True,
                        "skipped": True,
                        "message": "No build required (interpreted language or no build config)"
                    }

                # Install dependencies first
                install_result = self._install_dependencies(tmpdir, files)
                if not install_result['success']:
                    return {
                        "success": False,
                        "stage": "dependency_install",
                        "stdout": install_result.get('stdout', ''),
                        "stderr": install_result.get('stderr', ''),
                        "error": "Failed to install dependencies"
                    }

                # Run build command
                logger.info(f"Running build command: {build_command}")
                result = subprocess.run(
                    build_command,
                    shell=True,
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=120,  # 2 minutes
                    text=True
                )

                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "command": build_command
                }

            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "Build timeout after 120 seconds",
                    "stderr": "Build command timed out"
                }
            except Exception as e:
                logger.error(f"Build failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "stderr": str(e)
                }

    def _detect_build_command(self, files: Dict[str, str]) -> str:
        """Auto-detect appropriate build command based on project files"""

        # Node.js/TypeScript projects
        if 'package.json' in files:
            try:
                pkg = json.loads(files['package.json'])
                scripts = pkg.get('scripts', {})

                # Check for build script
                if 'build' in scripts:
                    return 'npm run build'
                # Check for compile script
                elif 'compile' in scripts:
                    return 'npm run compile'
            except json.JSONDecodeError:
                pass

            # TypeScript project without build script
            if any(f.endswith('.ts') for f in files.keys()):
                return 'npx tsc --noEmit'  # Type check only

        # Python projects - usually no build needed
        # But we can check syntax
        if any(f.endswith('.py') for f in files.keys()):
            return None  # Python is interpreted, no build needed

        # Java projects
        if 'pom.xml' in files:
            return 'mvn compile'
        elif 'build.gradle' in files:
            return 'gradle build'

        # Go projects
        if 'go.mod' in files:
            return 'go build'

        # Rust projects
        if 'Cargo.toml' in files:
            return 'cargo build'

        # No build needed
        return None

    def _install_dependencies(self, tmpdir: str, files: Dict[str, str]) -> Dict[str, Any]:
        """Install dependencies before building"""
        try:
            if 'package.json' in files:
                # Node.js project
                logger.info("Installing npm dependencies...")
                result = subprocess.run(
                    ['npm', 'install', '--legacy-peer-deps'],
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=180,  # 3 minutes for npm install
                    text=True
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

            elif 'requirements.txt' in files:
                # Python project
                logger.info("Installing pip dependencies...")
                result = subprocess.run(
                    ['pip', 'install', '-r', 'requirements.txt', '--quiet'],
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=180,
                    text=True
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

            # No dependencies to install
            return {"success": True}

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Dependency installation timeout"
            }
        except FileNotFoundError:
            # npm or pip not available
            logger.warning("Package manager not found, skipping dependency install")
            return {"success": True, "skipped": True}
        except Exception as e:
            logger.error(f"Dependency installation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
