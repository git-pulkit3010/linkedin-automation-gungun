#!/usr/bin/env python3
"""Archive a LinkedIn draft in the user's workspace so every version is kept.

Standard library only. Writes <workspace>/posts/YYYY-MM-DD-<slug>.<ext> and prints
nothing but the absolute path of the file it wrote, so an agent can capture it and
feed it straight to post_linkedin.py --dry-run --file.

    python3 stage_draft.py --workspace /path/to/workspace --text "Post body..."
    python3 stage_draft.py --workspace /path/to/workspace --stdin < draft.txt
    python3 stage_draft.py --workspace /path/to/workspace --list
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

DEFAULT_SLUG = 'post'
MAX_SLUG_CHARS = 40
ALLOWED_EXTENSIONS = ('md', 'txt')


def slugify(text):
    """First non-empty line -> lowercase, hyphen-separated, max 40 characters."""
    first_line = next((line.strip() for line in (text or '').splitlines() if line.strip()), '')
    slug = re.sub(r'[^a-z0-9]+', '-', first_line.lower()).strip('-')
    slug = slug[:MAX_SLUG_CHARS].strip('-')
    return slug or DEFAULT_SLUG


def normalize_ext(ext):
    ext = (ext or 'md').lstrip('.').lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError('Unsupported extension: .' + ext + '. Use .md or .txt.')
    return ext


def posts_dir(workspace):
    return Path(workspace).expanduser() / 'posts'


def target_path(workspace, body, slug=None, ext='md', force=False, today=None):
    """Path to write: date + slug, suffixed -2, -3, ... instead of overwriting."""
    directory = posts_dir(workspace)
    day = (today or datetime.date.today()).isoformat()
    stem = day + '-' + (slugify(slug) if slug else slugify(body))
    extension = normalize_ext(ext)
    path = directory / (stem + '.' + extension)
    if force or not path.exists():
        return path
    counter = 2
    while True:
        candidate = directory / '{}-{}.{}'.format(stem, counter, extension)
        if not candidate.exists():
            return candidate
        counter += 1


def write_draft(workspace, body, slug=None, ext='md', force=False, today=None):
    """Write the draft and return the absolute path actually written."""
    if not body.strip():
        raise ValueError('Draft body is empty.')
    directory = posts_dir(workspace)
    directory.mkdir(parents=True, exist_ok=True)
    path = target_path(workspace, body, slug=slug, ext=ext, force=force, today=today)
    text = body if body.endswith('\n') else body + '\n'
    path.write_text(text, encoding='utf-8')
    return path.resolve()


def list_drafts(workspace):
    """Staged drafts as (name, size, modified date), newest name first."""
    directory = posts_dir(workspace)
    if not directory.is_dir():
        return []
    rows = []
    for path in sorted(directory.iterdir(), reverse=True):
        if path.is_file() and path.suffix.lower() in ('.' + ALLOWED_EXTENSIONS[0],
                                                      '.' + ALLOWED_EXTENSIONS[1]):
            stamp = datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
            rows.append((path.name, path.stat().st_size, stamp))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', required=True, metavar='DIR',
                        help='Workspace folder that should contain posts/')
    parser.add_argument('--text', metavar='BODY', help='Post body to archive')
    parser.add_argument('--stdin', action='store_true', help='Read the post body from stdin')
    parser.add_argument('--slug', metavar='SLUG', help='Override the filename slug')
    parser.add_argument('--ext', default='md', metavar='EXT', help='md (default) or txt')
    parser.add_argument('--force', action='store_true', help='Overwrite an existing draft')
    parser.add_argument('--list', dest='do_list', action='store_true',
                        help='List staged drafts instead of writing')
    args = parser.parse_args()
    try:
        if args.do_list:
            for name, size, stamp in list_drafts(args.workspace):
                print('{}\t{} bytes\t{}'.format(name, size, stamp))
            return 0
        if args.text and args.stdin:
            raise ValueError('Supply either --text or --stdin, not both.')
        if not args.text and not args.stdin:
            raise ValueError('Supply either --text or --stdin.')
        body = sys.stdin.read() if args.stdin else args.text
        print(write_draft(args.workspace, body, slug=args.slug, ext=args.ext,
                          force=args.force))
        return 0
    except (ValueError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
