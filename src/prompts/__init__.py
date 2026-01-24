"""
Prompts for Issue Agent
"""

# Read prompt files and expose as constants
import os
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

def _read_prompt_file(filename: str) -> str:
    """Read a prompt file"""
    filepath = _PROMPTS_DIR / filename
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

# Issue Analysis Prompt
ISSUE_ANALYSIS_SYSTEM_PROMPT = _read_prompt_file('issue_analysis.md')

# Fix Generation Prompt Template
FIX_GENERATION_PROMPT_TEMPLATE = _read_prompt_file('fix_generation.md')
