#!/usr/bin/env python3
"""Read-only setup checker for the linkedin-publisher skill.

Verifies the Python version, the skill layout, which .env file is in play, and which
configuration keys are present — values are always masked. Nothing is published and
no file is written.

    python3 doctor.py
    python3 doctor.py --workspace /path/to/workspace
    python3 doctor.py --check-api        # makes one live Composio request

Exits 0 when the essentials are present, 1 when something required is missing.
Standard library only — there is nothing to pip install.
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

MIN_PYTHON = (3, 8)
REQUIRED_KEYS = ('COMPOSIO_API_KEY', 'COMPOSIO_USER_ID')
OPTIONAL_KEYS = ('COMPOSIO_CONNECTED_ACCOUNT_ID', 'GOOGLEDRIVE_CONNECTED_ACCOUNT_ID',
                 'LINKEDIN_AUTHOR_URN',
                 'LINKEDIN_AUTH_CONFIG_ID', 'GOOGLEDRIVE_AUTH_CONFIG_ID')
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent


def load_cli():
    """Import the sibling post_linkedin.py, which is not an importable package name."""
    path = SCRIPTS_DIR / 'post_linkedin.py'
    if not path.is_file():
        raise FileNotFoundError('Missing script: ' + str(path))
    spec = importlib.util.spec_from_file_location('linkedin_publisher_cli', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describe_value(value):
    if not value:
        return 'MISSING'
    return 'set ({} characters, masked)'.format(len(value))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', metavar='DIR',
                        help='Workspace folder that should contain posts/ (default: parent of the skill)')
    parser.add_argument('--env-file', metavar='PATH', help='Check this .env instead of discovery')
    parser.add_argument('--check-api', action='store_true',
                        help='Make one live Composio request (skipped if the network is down)')
    args = parser.parse_args()

    failures = []
    print('linkedin-publisher doctor')
    print('=========================')

    version = '.'.join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] >= MIN_PYTHON:
        print('[OK]   Python {} (needs {}.{}+)'.format(version, MIN_PYTHON[0], MIN_PYTHON[1]))
    else:
        print('[FAIL] Python {} is too old (needs {}.{}+)'.format(version, MIN_PYTHON[0], MIN_PYTHON[1]))
        failures.append('python')

    print('[OK]   this script      : ' + str(Path(__file__).resolve()))
    print('[OK]   skill root       : ' + str(SKILL_ROOT))
    print('       no third-party packages are required (standard library only)')

    try:
        cli = load_cli()
    except Exception as exc:  # pragma: no cover - layout problem
        print('[FAIL] post_linkedin.py : cannot load ({})'.format(exc))
        print('\nRESULT: FAILED (1 problem)')
        return 1
    print('[OK]   post_linkedin.py : ' + str(SCRIPTS_DIR / 'post_linkedin.py'))

    env_path, env_source = None, 'none'
    try:
        env_path, env_source = cli.resolve_env_file(args.env_file, skill_root=SKILL_ROOT)
    except cli.SetupError as exc:
        print('[FAIL] env file         : ' + str(exc))
        failures.append('env-file')
    if env_path:
        print('[OK]   env file         : {} (from {})'.format(env_path, env_source))
    else:
        print('[WARN] env file         : none found — falling back to process environment')

    file_values = {}
    if env_path:
        try:
            file_values = cli.load_env_file(env_path)
        except cli.SetupError as exc:
            print('[FAIL] ' + str(exc))
            failures.append('env-parse')

    def effective(key):
        return (os.environ.get(key) or file_values.get(key) or '').strip()

    for key in REQUIRED_KEYS:
        value = effective(key)
        if value:
            print('[OK]   {} : {}'.format(key, describe_value(value)))
        else:
            print('[FAIL] {} : {}'.format(key, describe_value(value)))
            failures.append(key)
    for key in OPTIONAL_KEYS:
        print('[info] {} : {}'.format(key, 'present' if effective(key) else 'absent'))

    workspace = Path(args.workspace).expanduser() if args.workspace else SKILL_ROOT.parent
    staged = workspace / 'posts'
    print('[info] posts directory  : {} ({})'.format(staged, 'exists' if staged.is_dir() else 'will be created on first draft'))

    if args.check_api:
        key = effective('COMPOSIO_API_KEY')
        if not key:
            print('[SKIP] live API check   : no COMPOSIO_API_KEY to test with')
        else:
            try:
                tools = cli.ComposioAPI(key).linkedin_tools()
                slugs = {tool.get('slug') for tool in tools}
                if cli.POST_SLUG in slugs:
                    print('[OK]   live API check   : COMPOSIO_API_KEY accepted, posting tool found')
                else:
                    print('[WARN] live API check   : key accepted but {} is not in the catalog'.format(cli.POST_SLUG))
            except cli.SetupError as exc:
                message = str(exc)
                if message.startswith('Network error'):
                    print('[SKIP] live API check   : network unavailable — ' + message)
                else:
                    print('[FAIL] live API check   : ' + message)
                    failures.append('api')

    print('')
    if failures:
        print('RESULT: FAILED ({} problem(s): {})'.format(len(failures), ', '.join(failures)))
        print('Next step: fix the items above, then run doctor.py again.')
        return 1
    print('RESULT: READY — dry runs and publishes can proceed.')
    print('Preview without posting: python3 {} --dry-run --file <draft.md> --json'.format(
        SCRIPTS_DIR / 'post_linkedin.py'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
