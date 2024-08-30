import configparser
import os
import sys

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


def load_config(config_file=CONFIG_FILE):
    config = configparser.ConfigParser()
    config.read(config_file)
    return config


def generate_default_config(config_file=CONFIG_FILE):
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
        'chore': 'Other changes that don’t modify src or test files',
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


def main():
    if len(sys.argv) < 2:
        print("Usage: ccgen.py [generate-config|commit]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "generate-config":
        generate_default_config()
    elif command == "commit":
        if not os.path.exists(CONFIG_FILE):
            print(f"Config file '{CONFIG_FILE}' not found. Please run 'ccgen.py generate-config' to generate it first.")
            sys.exit(1)
        config = load_config()
        interactive_commit(config)
    else:
        print("Invalid command. Usage: ccgen.py [generate-config|commit]")


if __name__ == "__main__":
    main()
