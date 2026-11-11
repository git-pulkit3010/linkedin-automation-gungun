#!/usr/bin/env python3
"""Stage a Google Drive draft that Cowork's native Drive connector retrieved.

LinkedIn still goes through Composio; Google Drive does not. The agent uses its own
connected Drive connector (the native Google Drive plugin in Claude Cowork) to find
the draft the user means, export or download its text, and save it to a local file.
This script then reads that file, validates it, and archives it in
<workspace>/posts/ so the same stage -> preview -> approve -> publish flow applies to
every source. It never contacts Composio or Google Drive and never publishes.

    # 1. with the Drive connector, locate the draft and save its text, e.g.
    #    export the Google Doc as plain text into ./drive-download.md
    # 2. archive it through this script:
    python3 drive_draft.py --file ./drive-download.md \
        --name "Client Launch Post" --id FILE_ID --workspace /path/to/workspace --json
    python3 drive_draft.py --stdin --name "Client Launch Post" \
        --workspace /path/to/workspace --json < exported.txt
"""

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

SCRIPT_DIR = Path(__file__).resolve().parent
READABLE_SUFFIXES = {'.txt', '.md', '.docx'}
STAGE_SUFFIXES = {'.txt', '.md'}
DRIVE_ID_RE = re.compile(r'[A-Za-z0-9_-]+')


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, str(SCRIPT_DIR / (name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage_extension(name):
    """Keep .txt/.md sources in their own extension; everything else becomes .md."""
    if name:
        suffix = Path(name).suffix.lower()
        if suffix in STAGE_SUFFIXES:
            return suffix[1:]
    return 'md'


def validate_source(name, file_id, link):
    """Guard the optional Drive provenance the agent passes through."""
    source = {}
    if name:
        name = name.strip()
        if not name:
            raise ValueError('--name must not be blank.')
        if len(name) > 200:
            raise ValueError('--name is too long to be a Drive document name.')
        source['name'] = name
    if file_id:
        if not DRIVE_ID_RE.fullmatch(file_id) or len(file_id) > 100:
            raise ValueError('--id must be a Google Drive file ID (letters, digits, - or _).')
        source['id'] = file_id
    if link:
        link = link.strip()
        if not re.fullmatch(r'https://[^\s]+', link) or len(link) > 500:
            raise ValueError('--link must be an HTTPS Google Drive or Google Docs URL.')
        source['link'] = link
    return source


def read_source(path, cli):
    """Extract text from the file the Drive connector handed over."""
    suffix = path.suffix.lower()
    if suffix not in READABLE_SUFFIXES:
        raise ValueError('Unsupported Drive file type: ' + suffix + '. A Google Doc exported as '
                         'plain text, or a stored .txt, .md, or .docx file.')
    try:
        return cli.read_post_bytes(path.read_bytes(), suffix)
    except (OSError, UnicodeError, zipfile.BadZipFile, KeyError,
            ElementTree.ParseError) as exc:
        raise ValueError(f'Cannot read the Drive download {path}: {exc}') from exc


def stage(workspace, text, source, stage_script, ext):
    if not text.strip():
        raise ValueError('The Google Drive draft contains no text.')
    slug = source.get('name')
    path = stage_script.write_draft(workspace, text, slug=slug, ext=ext)
    content = path.read_text(encoding='utf-8')
    if not content.strip():
        raise ValueError(f'Staged file {path} contains no text.')
    return {'path': str(path), 'char_count': len(content)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--file', metavar='PATH',
                        help='Local file saved from the Drive connector (export or download)')
    source.add_argument('--stdin', action='store_true',
                        help='Read the Drive export piped on standard input')
    parser.add_argument('--name', metavar='NAME',
                        help='Drive document name, for the staged filename and provenance')
    parser.add_argument('--id', metavar='ID', help='Drive file ID, for provenance only')
    parser.add_argument('--link', metavar='URL', help='Drive/Docs link, for provenance only')
    parser.add_argument('--workspace', metavar='DIR', required=True,
                        help='Workspace that holds the posts/ archive')
    parser.add_argument('--json', action='store_true', help='Print one JSON object')
    args = parser.parse_args()
    cli = load_script('post_linkedin')
    stage_script = load_script('stage_draft')
    try:
        drive = validate_source(args.name, args.id, args.link)
        if args.file:
            path = Path(args.file).expanduser()
            if not path.is_file():
                raise ValueError(f'Drive download not found: {path}')
            text = read_source(path, cli)
            ext = path.suffix.lower() if path.suffix.lower() in STAGE_SUFFIXES else 'md'
        else:
            raw = sys.stdin.buffer.read()
            if not raw.strip():
                raise ValueError('No text was piped to --stdin.')
            try:
                text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
            except UnicodeDecodeError as exc:
                raise ValueError('The piped Drive export is not valid UTF-8 text: '
                                 + str(exc)) from exc
            ext = stage_extension(args.name)
        staged = stage(args.workspace, text, drive, stage_script, ext)
        output = {'mode': 'import', 'source': drive, **staged}
        if args.json:
            print(json.dumps(output, ensure_ascii=False))
        else:
            print(staged['path'])
        return 0
    except (ValueError, OSError, UnicodeError, cli.SetupError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
