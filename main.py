import configparser
import os
import sys
import subprocess
import re
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import calendar

CONFIG_FILE = 'ccgen.ini'

DEFAULT_TYPES = {
    'feat': 'A new feature',
    'fix': 'A bug fix',
}

class Command:
    def __init__(self, prompt, help_info, is_required=False):
        self.prompt = prompt
        self.help_info = help_info
        self.is_required = is_required

    def get_input(self, allowed_values=None):
        while True:
            user_input = input(f"{self.prompt} (type 'help' for more info): ").strip()
            if user_input.lower() == 'help':
                self.print_help()
                continue
            if not self.is_required and user_input == '':
                return None
            if self.is_required and user_input == '':
                print("This field is required. Please enter a value.")
                continue
            if allowed_values and user_input not in allowed_values:
                print(f"Invalid input. Please choose from the allowed values: {', '.join(allowed_values)}")
                continue
            return user_input

    def print_help(self):
        print(self.help_info)


class CommitParser:
    def __init__(self):
        # Pattern to match conventional commits
        self.commit_pattern = re.compile(
            r'^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<description>.+)$'
        )
        self.breaking_change_pattern = re.compile(r'^BREAKING CHANGE:\s*(.+)$', re.MULTILINE)

    def parse_commit(self, commit_message: str) -> Dict:
        """Parse a conventional commit message and extract its components."""
        lines = commit_message.strip().split('\n')
        header = lines[0]
        body = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ''
        
        match = self.commit_pattern.match(header)
        if not match:
            return {
                'type': 'unknown',
                'scope': None,
                'description': header,
                'breaking': False,
                'body': body,
                'valid': False
            }
        
        # Check for breaking changes in body
        breaking_in_body = bool(self.breaking_change_pattern.search(body))
        breaking_change_description = None
        if breaking_in_body:
            breaking_match = self.breaking_change_pattern.search(body)
            breaking_change_description = breaking_match.group(1) if breaking_match else None
        
        return {
            'type': match.group('type'),
            'scope': match.group('scope'),
            'description': match.group('description'),
            'breaking': bool(match.group('breaking')) or breaking_in_body,
            'breaking_description': breaking_change_description,
            'body': body,
            'valid': True
        }


class GitHelper:
    def __init__(self, git_dir: str = None):
        """Initialize GitHelper with optional git directory."""
        self.git_dir = git_dir or os.getcwd()
        self.git_args = ['-C', self.git_dir] if self.git_dir != os.getcwd() else []
    
    def _run_git_command(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a git command with the specified directory."""
        full_cmd = ['git'] + self.git_args + cmd
        return subprocess.run(full_cmd, **kwargs)
    
    def is_git_repo(self) -> bool:
        """Check if the target directory is a git repository."""
        try:
            self._run_git_command(['rev-parse', '--git-dir'], 
                                capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False
    
    def get_commits_since_tag(self, tag: str = None) -> List[Dict]:
        """Get all commits since a specific tag (or all commits if no tag)."""
        try:
            if tag:
                cmd = ['log', f'{tag}..HEAD', '--pretty=format:%H|%s|%an|%ad|%B', '--date=short']
            else:
                cmd = ['log', '--pretty=format:%H|%s|%an|%ad|%B', '--date=short']
            
            result = self._run_git_command(cmd, capture_output=True, text=True, check=True)
            commits = []
            
            for commit_block in result.stdout.split('\n\n'):
                if not commit_block.strip():
                    continue
                    
                lines = commit_block.strip().split('\n')
                if not lines:
                    continue
                    
                first_line = lines[0]
                parts = first_line.split('|', 4)
                if len(parts) < 4:
                    continue
                
                commit_hash, subject, author, date = parts[:4]
                body = '\n'.join(lines[1:]) if len(lines) > 1 else ''
                full_message = subject + '\n' + body if body else subject
                
                commits.append({
                    'hash': commit_hash,
                    'subject': subject,
                    'author': author,
                    'date': date,
                    'full_message': full_message
                })
            
            return commits
        except subprocess.CalledProcessError:
            return []
    
    def get_all_commits(self) -> List[Dict]:
        """Get all commits in the repository."""
        try:
            cmd = ['log', '--pretty=format:%H|%s|%an|%ad|%B', '--date=short']
            
            result = self._run_git_command(cmd, capture_output=True, text=True, check=True)
            commits = []
            
            for commit_block in result.stdout.split('\n\n'):
                if not commit_block.strip():
                    continue
                    
                lines = commit_block.strip().split('\n')
                if not lines:
                    continue
                    
                first_line = lines[0]
                parts = first_line.split('|', 4)
                if len(parts) < 4:
                    continue
                
                commit_hash, subject, author, date = parts[:4]
                body = '\n'.join(lines[1:]) if len(lines) > 1 else ''
                full_message = subject + '\n' + body if body else subject
                
                commits.append({
                    'hash': commit_hash,
                    'subject': subject,
                    'author': author,
                    'date': date,
                    'full_message': full_message
                })
            
            return commits
        except subprocess.CalledProcessError:
            return []
    
    def get_latest_tag(self) -> Optional[str]:
        """Get the latest git tag."""
        try:
            result = self._run_git_command(['describe', '--tags', '--abbrev=0'], 
                                         capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
    
    def tag_exists(self, tag: str) -> bool:
        """Check if a git tag exists."""
        try:
            self._run_git_command(['rev-parse', f'refs/tags/{tag}'], 
                                capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False


class SemanticVersioner:
    def __init__(self):
        self.parser = CommitParser()
    
    def parse_version(self, version_string: str) -> Tuple[int, int, int]:
        """Parse a semantic version string into major, minor, patch components."""
        # Remove 'v' prefix if present
        version_string = version_string.lstrip('v')
        
        # Handle pre-release versions by taking only the core version
        core_version = version_string.split('-')[0].split('+')[0]
        
        try:
            parts = core_version.split('.')
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return major, minor, patch
        except (ValueError, IndexError):
            return 0, 0, 0
    
    def determine_single_commit_bump(self, commit: Dict) -> str:
        """Determine the version bump type for a single commit."""
        parsed = self.parser.parse_commit(commit['full_message'])
        
        if parsed['breaking']:
            return 'major'
        elif parsed['type'] == 'feat':
            return 'minor'
        elif parsed['type'] == 'fix':
            return 'patch'
        else:
            return 'patch'  # Default to patch for any changes
    
    def apply_version_bump(self, current_version: Tuple[int, int, int], bump_type: str) -> Tuple[int, int, int]:
        """Apply a version bump to the current version."""
        major, minor, patch = current_version
        
        if bump_type == 'major':
            return (major + 1, 0, 0)
        elif bump_type == 'minor':
            return (major, minor + 1, 0)
        else:  # patch
            return (major, minor, patch + 1)

    def calculate_version(self, commits: List[Dict]) -> str:
        return self.calculate_next_version("0.0.0", commits)
    
    def calculate_next_version(self, current_version: str, commits: List[Dict]) -> str:
        """Calculate the next semantic version based on commits processed iteratively."""
        # Parse the current version
        version_tuple = self.parse_version(current_version)
        
        # Sort commits by timestamp (assuming commits have a timestamp field)
        # If commits don't have timestamps, they should be pre-sorted chronologically
        sorted_commits = sorted(commits, key=lambda c: c.get('timestamp', 0))
        
        # Process each commit iteratively
        for commit in sorted_commits:
            bump_type = self.determine_single_commit_bump(commit)
            version_tuple = self.apply_version_bump(version_tuple, bump_type)
        
        # Format the final version
        major, minor, patch = version_tuple
        return f"{major}.{minor}.{patch}"

def generate_changelog(git_dir=None):
    """Generate a changelog based on commits grouped by month from the first commit."""
    git_helper = GitHelper(git_dir)
    
    # Check if it's a git repository
    if not git_helper.is_git_repo():
        print(f"Error: '{git_helper.git_dir}' is not a git repository.")
        return
    
    print(f"Working with git repository: {git_helper.git_dir}")
    
    changelog_generator = ChangelogGenerator()
    
    # Get all commits from the beginning
    all_commits = git_helper.get_all_commits()
    
    if not all_commits:
        print("No commits found in the repository.")
        return
    
    # Group commits by month and calculate versions
    monthly_data = changelog_generator.group_commits_by_month(all_commits)
    
    # Generate changelog
    changelog = changelog_generator.generate_monthly_changelog(monthly_data)
    
    # Write to file in the git directory
    changelog_file = os.path.join(git_helper.git_dir, 'CHANGELOG.md')
    
    with open(changelog_file, 'w') as f:
        f.write(changelog)
    
    print(f"Changelog generated and saved to {changelog_file}")



def generate_default_config(config_file=CONFIG_FILE, git_dir=None):
    """Generate default configuration file in the specified directory."""
    if git_dir:
        config_file = os.path.join(git_dir, CONFIG_FILE)
    
    config = configparser.ConfigParser()

    # Default types and descriptions (excluding feat and fix)
    config['types'] = {
        'docs': 'Documentation only changes',
        'style': 'Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc.)',
        'refactor': 'A code change that neither fixes a bug nor adds a feature',
        'perf': 'A code change that improves performance',
        'test': 'Adding missing tests or correcting existing tests',
        'build': 'Changes that affect the build system or external dependencies (example scopes: gulp, broccoli, npm)',
        'ci': 'Changes to our CI configuration files and scripts (example scopes: Travis, Circle, BrowserStack, SauceLabs)',
        'chore': "Other changes that don't modify src or test files",
        'revert': 'Reverts a previous commit'
    }

    # Default scopes and descriptions
    config['scopes'] = {
        'ui': 'Changes to the user interface',
        'backend': 'Changes to backend logic',
        'api': 'Changes to the API',
        'cli': 'Changes to the CLI',
        'docs': 'Changes to documentation'
    }

    # Ensure directory exists
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    
    with open(config_file, 'w') as configfile:
        config.write(configfile)
    print(f"Default config file '{config_file}' generated successfully.")


def format_commit_message(commit_type, scope, description, detailed_message, breaking_change, issue_reference):
    commit_message = f"{commit_type}"
    if scope:
        commit_message += f"({scope})"
    commit_message += f": {description}"
    
    if detailed_message:
        commit_message += f"\n\n{detailed_message}"
    
    if breaking_change:
        commit_message += f"\n\nBREAKING CHANGE: {breaking_change}"
    
    if issue_reference:
        commit_message += f"\n\nCloses: {issue_reference}"
    
    return commit_message


def interactive_commit(config):
    print("Conventional Commits Interactive Helper")

    # Combine default types with types from config file
    commit_types = {**DEFAULT_TYPES, **config['types']}
    scopes = config['scopes']

    # Get commit type
    commit_type = Command(
        prompt="Select the type of change you are committing",
        help_info="\n".join([f"{key} - {value}" for key, value in commit_types.items()]),
        is_required=True
    ).get_input(allowed_values=commit_types.keys())

    # Get scope (optional)
    scope = Command(
        prompt="Enter the scope of the change (optional, leave empty to skip)",
        help_info="\n".join([f"{key} - {value}" for key, value in scopes.items()])
    ).get_input(allowed_values=scopes.keys())

    # Get short description
    description = Command(
        prompt="Enter a short description of the change",
        help_info="A brief summary of the change being made. It should be concise and informative.",
        is_required=True
    ).get_input()

    # Get detailed message (optional)
    detailed_message = Command(
        prompt="Enter a longer description of the change (optional, leave empty to skip)",
        help_info="An extended description that provides additional context about the change."
    ).get_input()

    # Check for breaking change
    breaking_change = None
    if Command(
        prompt="Does this commit introduce breaking changes? (y/n)",
        help_info="Indicate whether this commit introduces a breaking change."
    ).get_input(allowed_values=['y', 'n']) == 'y':
        breaking_change = input("Describe the breaking changes: ").strip()

    # Get issue reference (optional)
    issue_reference = Command(
        prompt="Reference any issues this commit closes (optional, leave empty to skip)",
        help_info="Reference an issue or bug that this commit resolves."
    ).get_input()

    # Format and print the commit message
    commit_message = format_commit_message(commit_type, scope, description, detailed_message, breaking_change, issue_reference)
    
    print("\nGenerated Commit Message:\n")
    print(commit_message)
    print("\nReady to use this commit message?")


def calculate_version(git_dir=None):
    """Calculate the current semantic version based on all commits in the repository."""
    git_helper = GitHelper(git_dir)
    
    # Check if it's a git repository
    if not git_helper.is_git_repo():
        print(f"Error: '{git_helper.git_dir}' is not a git repository.")
        return
    
    print(f"Working with git repository: {git_helper.git_dir}")
    
    versioner = SemanticVersioner()
    
    # Start from version 0.0.0
    current_version = "0.0.0"
    print(f"Starting version: {current_version}")
    
    # Get all commits in the repository
    commits = git_helper.get_all_commits()  # Assuming this method exists
    
    if not commits:
        print("No commits found in the repository.")
        print(f"Current version: {current_version}")
        return
    
    print(f"Found {len(commits)} total commits.")
    
    # Calculate current version based on all commits
    computed_version = versioner.calculate_next_version(current_version, commits)
    
    print(f"\nComputed current version: {computed_version}")
    
    # Show breakdown of commits based on conventional commits
    parser = CommitParser()
    breaking_changes = []
    features = []
    fixes = []
    others = []
    
    for commit in commits:
        parsed = parser.parse_commit(commit['full_message'])
        if parsed['breaking']:
            breaking_changes.append(commit)
        elif parsed['type'] == 'feat':
            features.append(commit)
        elif parsed['type'] == 'fix':
            fixes.append(commit)
        else:
            others.append(commit)
    
    # Display commit breakdown
    if breaking_changes:
        print(f"\n💥 Breaking changes: {len(breaking_changes)}")
    if features:
        print(f"✨ Features: {len(features)}")
    if fixes:
        print(f"🐛 Bug fixes: {len(fixes)}")
    if others:
        print(f"🔧 Other changes: {len(others)}")
    
    return computed_version


class ChangelogGenerator:
    def __init__(self):
        self.parser = CommitParser()
        self.versioner = SemanticVersioner()
    
    def group_commits_by_month(self, commits: List[Dict]) -> List[Dict]:
        """Group commits by month and calculate versions progressively."""
        # Sort commits by date (oldest first)
        sorted_commits = sorted(commits, key=lambda x: x['date'])
        
        # Group by year-month
        monthly_commits = defaultdict(list)
        
        for commit in sorted_commits:
            # Parse the commit date (handle both formats)
            try:
                # Try with time first
                commit_date = datetime.strptime(commit['date'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                # Fall back to date only
                commit_date = datetime.strptime(commit['date'], '%Y-%m-%d')
            
            year_month = commit_date.strftime('%Y-%m')
            monthly_commits[year_month].append(commit)
        
        # Calculate versions progressively
        monthly_data = []
        current_version = "0.0.0"
        
        # Sort months chronologically
        sorted_months = sorted(monthly_commits.keys())
        
        for year_month in sorted_months:
            month_commits = monthly_commits[year_month]
            
            # Calculate next version based on commits in this month
            next_version = self.versioner.calculate_next_version(current_version, month_commits)
            
            # Parse the year-month for display
            year, month = year_month.split('-')
            month_name = calendar.month_name[int(month)]
            
            monthly_data.append({
                'year_month': year_month,
                'display_date': f"{month_name} {year}",
                'commits': month_commits,
                'version': next_version
            })
            
            current_version = next_version
        
        return monthly_data
    
    def generate_monthly_changelog(self, monthly_data: List[Dict]) -> str:
        """Generate a changelog from monthly grouped commits."""
        changelog = "# Changelog\n\n"
        
        # Process months in reverse chronological order (newest first)
        for month_data in reversed(monthly_data):
            changelog += self.generate_month_section(
                month_data['commits'], 
                month_data['version'], 
                month_data['display_date']
            )
        
        return changelog
    
    def generate_month_section(self, commits: List[Dict], version: str, display_date: str) -> str:
        """Generate a changelog section for a specific month."""
        section = f"## [{version}] - {display_date}\n\n"
        
        # Group commits by type
        grouped_commits = {
            'feat': [],
            'fix': [],
            'breaking': [],
            'other': []
        }
        
        for commit in commits:
            parsed = self.parser.parse_commit(commit['full_message'])
            
            if parsed['breaking']:
                grouped_commits['breaking'].append({
                    'commit': commit,
                    'parsed': parsed
                })
            elif parsed['type'] == 'feat':
                grouped_commits['feat'].append({
                    'commit': commit,
                    'parsed': parsed
                })
            elif parsed['type'] == 'fix':
                grouped_commits['fix'].append({
                    'commit': commit,
                    'parsed': parsed
                })
            elif parsed['valid']:
                grouped_commits['other'].append({
                    'commit': commit,
                    'parsed': parsed
                })
        
        # Add breaking changes first
        if grouped_commits['breaking']:
            section += "### 💥 BREAKING CHANGES\n\n"
            for item in grouped_commits['breaking']:
                parsed = item['parsed']
                scope_str = f"**{parsed['scope']}**: " if parsed['scope'] else ""
                section += f"- {scope_str}{parsed['description']}\n"
                if parsed['breaking_description']:
                    section += f"  - {parsed['breaking_description']}\n"
            section += "\n"
        
        # Add features
        if grouped_commits['feat']:
            section += "### ✨ Features\n\n"
            for item in grouped_commits['feat']:
                parsed = item['parsed']
                scope_str = f"**{parsed['scope']}**: " if parsed['scope'] else ""
                section += f"- {scope_str}{parsed['description']}\n"
            section += "\n"
        
        # Add bug fixes
        if grouped_commits['fix']:
            section += "### 🐛 Bug Fixes\n\n"
            for item in grouped_commits['fix']:
                parsed = item['parsed']
                scope_str = f"**{parsed['scope']}**: " if parsed['scope'] else ""
                section += f"- {scope_str}{parsed['description']}\n"
            section += "\n"
        
        # Add other changes
        if grouped_commits['other']:
            section += "### 🔧 Other Changes\n\n"
            for item in grouped_commits['other']:
                parsed = item['parsed']
                scope_str = f"**{parsed['scope']}**: " if parsed['scope'] else ""
                type_str = f"**{parsed['type']}**: " if parsed['type'] != 'unknown' else ""
                section += f"- {type_str}{scope_str}{parsed['description']}\n"
            section += "\n"
        
        return section


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Conventional Commits Generator - A tool for managing conventional commits, semantic versioning, and changelog generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ccgen.py commit                    # Interactive commit helper (current directory)
  python ccgen.py version                   # Calculate next version (current directory)
  python ccgen.py changelog                 # Generate changelog (current directory)
  python ccgen.py version --git-dir /path/to/repo  # Calculate version for specific repo
  python ccgen.py generate-config --git-dir /path/to/repo  # Generate config in specific repo
        """
    )
    
    parser.add_argument(
        'command',
        choices=['generate-config', 'commit', 'version', 'changelog'],
        help="""Command to execute:
  generate-config: Generate default configuration file
  commit:          Interactive commit message helper
  version:         Calculate next semantic version
  changelog:       Generate changelog from commits"""
    )
    
    parser.add_argument(
        '--git-dir',
        type=str,
        help='Path to git repository (defaults to current directory)'
    )
    
    args = parser.parse_args()
    
    # Validate git directory if provided
    if args.git_dir:
        if not os.path.exists(args.git_dir):
            print(f"Error: Directory '{args.git_dir}' does not exist.")
            sys.exit(1)
        if not os.path.isdir(args.git_dir):
            print(f"Error: '{args.git_dir}' is not a directory.")
            sys.exit(1)
    
    # Execute commands
    if args.command == "generate-config":
        generate_default_config(git_dir=args.git_dir)
    elif args.command == "commit":
        config_file = os.path.join(args.git_dir, CONFIG_FILE) if args.git_dir else CONFIG_FILE
        if not os.path.exists(config_file):
            print(f"Config file '{config_file}' not found. Please run 'python ccgen.py generate-config{' --git-dir ' + args.git_dir if args.git_dir else ''}' to generate it first.")
            sys.exit(1)
        config = load_config(git_dir=args.git_dir)
        interactive_commit(config)
    elif args.command == "version":
        calculate_version(git_dir=args.git_dir)
    elif args.command == "changelog":
        generate_changelog(git_dir=args.git_dir)


if __name__ == "__main__":
    main()
