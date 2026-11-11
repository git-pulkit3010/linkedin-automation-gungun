#!/usr/bin/env python3
"""Inspect, preview, or publish a LinkedIn text post with Composio's v3.1 REST API.

Standard library only — nothing to pip install. Python 3.8+.

Configuration lives in a .env file (see the skill's .env.example):
    COMPOSIO_API_KEY and COMPOSIO_USER_ID            required
    COMPOSIO_CONNECTED_ACCOUNT_ID                    optional account pin
    LINKEDIN_AUTHOR_URN                              optional author override

Read-only:
    python3 post_linkedin.py --inspect
    python3 post_linkedin.py --dry-run 'Hello LinkedIn'
    python3 post_linkedin.py --dry-run --file draft.docx --json
Publish (real post):
    python3 post_linkedin.py --publish --file draft.md
    python3 post_linkedin.py --publish 'Hello LinkedIn'
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

API_ROOT = 'https://backend.composio.dev/api/v3.1'
POST_SLUG = 'LINKEDIN_CREATE_LINKED_IN_POST'
PROFILE_SLUG = 'LINKEDIN_GET_MY_INFO'
DEFAULT_MAX_CHARS = 3000
HASHTAG_RE = re.compile(r'#[A-Za-z0-9_]+')

# The repo-root wrapper injects __skill_root__ before loading this source, so the
# skill folder is always the directory that owns .env, whatever is importing us.
SKILL_ROOT = Path(globals().get('__skill_root__') or Path(__file__).resolve().parent.parent)


class SetupError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Configuration (.env)
# --------------------------------------------------------------------------- #

def parse_env_text(text):
    """Parse .env text into a dict: KEY=value, export, quotes, and comments."""
    values = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            marker = value[0]
            end = value.find(marker, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            # An unquoted value ends at the first whitespace-led '#' comment.
            value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
        values[key] = value
    return values


def load_env_file(path):
    """Read and parse a .env file. Missing or unreadable files raise SetupError."""
    path = Path(path)
    try:
        return parse_env_text(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError) as exc:
        raise SetupError(f'Cannot read env file {path}: {exc}') from exc


def resolve_env_file(explicit=None, cwd=None, skill_root=None):
    """Return (path, source) for the first .env that exists, else (None, 'none').

    Order: --env-file, LINKEDIN_PUBLISHER_ENV_FILE, <skill root>/.env, <cwd>/.env,
    <cwd>/.env parent. An explicitly requested file that is missing is an error —
    silently falling back to another file would post from the wrong account.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise SetupError(f'Env file not found: {path} (--env-file)')
        return path, 'flag'
    override = os.environ.get('LINKEDIN_PUBLISHER_ENV_FILE', '').strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise SetupError('Env file from LINKEDIN_PUBLISHER_ENV_FILE not found: ' + str(path))
        return path, 'LINKEDIN_PUBLISHER_ENV_FILE'
    skill_root = Path(skill_root) if skill_root else SKILL_ROOT
    cwd = Path(cwd) if cwd else Path.cwd()
    for candidate, source in ((skill_root / '.env', 'skill root'),
                              (cwd / '.env', 'current directory'),
                              (cwd.parent / '.env', 'parent directory')):
        if candidate.is_file():
            return candidate, source
    return None, 'none'


def apply_env_file(path):
    """Fill in unset environment variables from a .env file (real env wins)."""
    values = load_env_file(path)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


# --------------------------------------------------------------------------- #
# Post content
# --------------------------------------------------------------------------- #

def read_post_file(path):
    """Read the post body from a UTF-8 document or Word document."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {'.txt', '.md', '.docx'}:
        raise SetupError('Unsupported post file type: ' + suffix + '. Use .txt, .md, or .docx.')
    try:
        content = read_post_bytes(path.read_bytes(), suffix)
    except (OSError, UnicodeError, zipfile.BadZipFile, KeyError,
            ElementTree.ParseError) as exc:
        raise SetupError(f'Cannot read post file {path}: {exc}') from exc
    if not content.strip():
        raise SetupError(f'Post file {path} contains no text.')
    return content


def read_post_bytes(data, suffix):
    """Extract text from downloaded Drive bytes using the same rules as local files."""
    if suffix == '.docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = ElementTree.fromstring(archive.read('word/document.xml'))
        word = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        paragraphs = []
        for paragraph in document.iter(word + 'p'):
            parts = []
            for element in paragraph.iter():
                if element.tag == word + 't':
                    parts.append(element.text or '')
                elif element.tag == word + 'tab':
                    parts.append('\t')
                elif element.tag in {word + 'br', word + 'cr'}:
                    parts.append('\n')
            paragraphs.append(''.join(parts))
        return '\n'.join(paragraphs)
    # Path.read_text() uses universal newlines; keep local and Drive inputs equal.
    return data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')


def extract_hashtags(text):
    """Hashtags in the post, in order of first appearance, without duplicates.

    LinkedIn shows #AI and #ai as the same tag, so the duplicate check ignores case
    while the first spelling the author wrote is the one kept.
    """
    found, seen = [], set()
    for tag in HASHTAG_RE.findall(text):
        if tag.lower() not in seen:
            seen.add(tag.lower())
            found.append(tag)
    return found


def check_length(text, max_chars):
    count = len(text)
    if count > max_chars:
        raise SetupError(f'Post is {count} characters, {count - max_chars} over the '
                         f'{max_chars}-character limit. Shorten the draft by at least '
                         f'{count - max_chars} characters, then dry-run it again.')
    return count


def parse_extra(raw):
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SetupError('--extra is invalid JSON: ' + str(exc)) from exc
    if not isinstance(extra, dict):
        raise SetupError('--extra must be a JSON object')
    return extra


# --------------------------------------------------------------------------- #
# Composio REST client (urllib only)
# --------------------------------------------------------------------------- #

class ComposioAPI:
    def __init__(self, key):
        if not key:
            raise SetupError('COMPOSIO_API_KEY is missing from .env')
        self.api_key = key

    def request(self, method, path, *, params=None, body=None):
        url = API_ROOT + path
        if params:
            url += '?' + urlencode(params, doseq=True)
        headers = {'x-api-key': self.api_key, 'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, default=str).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                status = response.getcode()
                raw = response.read()
        except HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read()
            except Exception:  # pragma: no cover - unreadable error body
                raw = b''
        except (URLError, OSError) as exc:
            raise SetupError(f'Network error contacting Composio: {exc}') from exc
        payload = (raw or b'').decode('utf-8', 'replace')
        try:
            result = json.loads(payload) if payload.strip() else {}
        except ValueError:
            result = {'message': payload[:1000]}
        if not 200 <= status < 300:
            detail = json.dumps(result, ensure_ascii=False, default=str)[:1800]
            hint = (' (Check COMPOSIO_API_KEY and project.)' if status in (401, 403)
                    else '')
            raise SetupError(f'Composio HTTP {status}: {detail}{hint}')
        return result

    def tool(self, slug):
        return self.request('GET', '/tools/' + quote(slug, safe=''),
                            params={'version': 'latest'})

    def linkedin_tools(self):
        result = self.request('GET', '/tools', params={
            'toolkit_slug': 'linkedin', 'toolkit_versions': 'latest', 'limit': 100})
        return result.get('items', [])

    def accounts(self):
        records, cursor = [], None
        for _ in range(25):
            params = {'limit': 100, 'account_type': 'ALL'}
            if cursor:
                params['cursor'] = cursor
            data = self.request('GET', '/connected_accounts', params=params)
            records.extend(data.get('items', []))
            next_cursor = data.get('next_cursor')
            if not next_cursor or next_cursor == cursor:
                return records
            cursor = next_cursor
        raise SetupError('Connected-account pagination exceeded 25 pages.')

    def execute(self, tool, user_id, account_id, arguments):
        slug = tool.get('slug')
        if not slug:
            raise SetupError('Tool is missing its slug.')
        payload = {'user_id': user_id,
                   'connected_account_id': account_id,
                   'arguments': arguments}
        # The metadata's actual dated version keeps the fetched schema and
        # execution definition aligned, avoiding the retired base version.
        version = tool.get('version')
        if isinstance(version, str) and re.fullmatch(r'\d{8}_\d{2}', version):
            payload['version'] = version
        else:
            payload['version'] = 'latest'  # v3.1 REST supports latest.
        result = self.request('POST', '/tools/execute/' + quote(slug, safe=''), body=payload)
        if not isinstance(result, dict):
            raise SetupError(f'Unexpected {slug} response: {str(result)[:500]}')
        if result.get('successful') is not True or result.get('error'):
            raise SetupError(f'{slug} execution failed: '
                             + json.dumps(result, ensure_ascii=False, default=str)[:2500])
        return result


def active_linkedin_account(api, user_id):
    if not user_id:
        raise SetupError('COMPOSIO_USER_ID is missing from .env.')
    records = api.accounts()
    linkedin = [a for a in records if (a.get('toolkit') or {}).get('slug', '').lower() == 'linkedin']
    matching = [a for a in linkedin if a.get('user_id') == user_id and a.get('status') == 'ACTIVE'
                and not a.get('is_disabled', False)]
    requested = os.getenv('COMPOSIO_CONNECTED_ACCOUNT_ID', '').strip()
    if requested:
        matching = [a for a in matching if a.get('id') == requested]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1:
        raise SetupError('Multiple ACTIVE LinkedIn accounts belong to this user. '
                         'Set COMPOSIO_CONNECTED_ACCOUNT_ID to one of: '
                         + ', '.join(a['id'] for a in matching))
    summary = [{'id': a.get('id'), 'user_id': a.get('user_id'), 'status': a.get('status')}
               for a in linkedin]
    raise SetupError('No ACTIVE LinkedIn connection matches COMPOSIO_USER_ID'
                     + (' and COMPOSIO_CONNECTED_ACCOUNT_ID' if requested else '')
                     + '. Available LinkedIn connections: '
                     + json.dumps(summary, default=str)
                     + '. Connect LinkedIn in the same Composio project and user_id.')


def author_from_profile(profile_response):
    """Extract a person URN conservatively; never guess a LinkedIn identity."""
    data = profile_response.get('data')
    while isinstance(data, dict):
        for name in ('author', 'personUrn', 'person_urn', 'urn', 'entityUrn'):
            raw = data.get(name)
            if isinstance(raw, str) and re.fullmatch(r'urn:li:person:[A-Za-z0-9_-]+', raw):
                return raw
        for name in ('person_id', 'personId', 'member_id', 'memberId', 'sub', 'id'):
            raw = data.get(name)
            if isinstance(raw, str) and re.fullmatch(r'urn:li:person:[A-Za-z0-9_-]+', raw):
                return raw
            if isinstance(raw, str) and re.fullmatch(r'[A-Za-z0-9_-]+', raw):
                return 'urn:li:person:' + raw
        nested = next((data[k] for k in ('data', 'result', 'profile', 'user')
                       if isinstance(data.get(k), dict)), None)
        data = nested
    return None


def get_author(api, user_id, account_id):
    author = os.getenv('LINKEDIN_AUTHOR_URN', '').strip()
    if author:
        if not re.fullmatch(r'urn:li:(person|organization):[A-Za-z0-9_-]+', author):
            raise SetupError('LINKEDIN_AUTHOR_URN must look like urn:li:person:abc123')
        return author
    try:
        info = api.execute(api.tool(PROFILE_SLUG), user_id, account_id, {})
    except SetupError as exc:
        raise SetupError('Could not retrieve LinkedIn member ID automatically: '
                         + str(exc) + '. Set LINKEDIN_AUTHOR_URN in .env.') from exc
    found = author_from_profile(info)
    if found:
        return found
    raise SetupError('GET_MY_INFO returned no recognizable LinkedIn person ID. '
                     'Set LINKEDIN_AUTHOR_URN=urn:li:person:<your-member-id> in .env. '
                     'Profile response field names: '
                     + str(list((info.get('data') or {}).keys())
                           if isinstance(info.get('data'), dict) else type(info.get('data')).__name__))


def tool_schema(tool):
    """Accept Composio's flat parameter mapping and ordinary JSON Schema."""
    raw = tool.get('input_parameters') or tool.get('inputParameters') or {}
    if not isinstance(raw, dict):
        raise SetupError('Unexpected input_parameters type: ' + type(raw).__name__)
    if isinstance(raw.get('properties'), dict):
        return raw['properties'], set(raw.get('required') or [])
    required = {k for k, v in raw.items() if isinstance(v, dict) and v.get('required') is True}
    return raw, required


def make_arguments(tool, text, author, extra):
    properties, required = tool_schema(tool)
    names = set(properties)
    text_field = next((f for f in ('commentary', 'text', 'content', 'body', 'message') if f in names), None)
    if not text_field:
        raise SetupError('Cannot identify post text parameter. Use --inspect to see current tool schema.')
    if 'author' not in names:
        raise SetupError('Tool has no author parameter; schema changed. Inspect before posting.')
    arguments = {'author': author, text_field: text}
    if 'visibility' in names:
        arguments['visibility'] = 'PUBLIC'
    if 'lifecycleState' in names:
        arguments['lifecycleState'] = 'PUBLISHED'
    if 'lifecycle_state' in names:
        arguments['lifecycle_state'] = 'PUBLISHED'
    unknown = set(extra) - names
    if unknown:
        raise SetupError('Unknown extra argument(s): ' + ', '.join(sorted(unknown))
                         + '. Available: ' + ', '.join(sorted(names)))
    arguments.update(extra)
    missing = required - set(arguments)
    if missing:
        raise SetupError('Missing required LinkedIn fields: ' + ', '.join(sorted(missing))
                         + '. Supply them via --extra JSON after inspecting the schema.')
    return arguments


def json_result(mode, env_path, account_id, user_id, author, tool, arguments, text,
                published=False, response=None):
    """The machine-readable envelope the agent parses when --json is set."""
    response = response or {}
    return {
        'mode': mode,
        'env_file': str(env_path) if env_path else None,
        'account_id': account_id,
        'user_id': user_id,
        'author': author,
        'toolkit_version': tool.get('version'),
        'visibility': arguments.get('visibility') or arguments.get('Visibility'),
        'text': text,
        'char_count': len(text),
        'hashtags': extract_hashtags(text),
        'arguments': arguments,
        'published': bool(published),
        'log_id': response.get('log_id'),
        'data': response.get('data'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--inspect', action='store_true', help='Read-only: list tool and input schema')
    group.add_argument('--dry-run', nargs='?', const='', metavar='TEXT',
                       help='Read-only profile lookup and post preview')
    group.add_argument('--publish', nargs='?', const='', metavar='TEXT',
                       help='Publish a real LinkedIn post')
    parser.add_argument('--file', metavar='PATH', help='Read post text from .txt, .md, or .docx')
    parser.add_argument('--extra', default='{}', help='Optional JSON object of extra post fields')
    parser.add_argument('--env-file', metavar='PATH', help='Use this .env file instead of discovery')
    parser.add_argument('--json', dest='as_json', action='store_true',
                        help='Machine-readable JSON on stdout (no other stdout output)')
    parser.add_argument('--max-chars', type=int, default=DEFAULT_MAX_CHARS, metavar='N',
                        help='Reject posts longer than N characters (default 3000)')
    args = parser.parse_args()
    try:
        if args.max_chars < 1:
            raise SetupError('--max-chars must be a positive whole number.')
        if args.inspect and args.file:
            raise SetupError('--file can only be used with --dry-run or --publish')
        inline_text = args.dry_run if args.dry_run is not None else args.publish
        post_text = ''
        if not args.inspect:
            if args.file and inline_text:
                raise SetupError('Supply either inline text or --file, not both.')
            if not args.file and not inline_text:
                raise SetupError('Supply either inline text or --file.')
            post_text = read_post_file(args.file) if args.file else inline_text
            check_length(post_text, args.max_chars)
        env_path, env_source = resolve_env_file(args.env_file)
        if env_path:
            apply_env_file(env_path)
        api = ComposioAPI(os.getenv('COMPOSIO_API_KEY'))
        listed = api.linkedin_tools()  # Verifies key and catalog access.
        available = {tool.get('slug') for tool in listed}
        if POST_SLUG not in available:
            raise SetupError('LinkedIn posting action absent from v3.1 latest catalog. '
                             'Available slugs: ' + ', '.join(sorted(available)))
        tool = api.tool(POST_SLUG)
        if args.inspect:
            print(json.dumps({'tool_slug': tool.get('slug'), 'version': tool.get('version'),
                              'input_parameters': tool.get('input_parameters')},
                             indent=2, ensure_ascii=False, default=str))
            return 0
        if not args.as_json:
            print('Env file: ' + (str(env_path) + ' (from ' + env_source + ')' if env_path
                                  else 'none found (using the process environment only)'))
        user_id = os.getenv('COMPOSIO_USER_ID', '').strip()
        account = active_linkedin_account(api, user_id)
        author = get_author(api, user_id, account['id'])
        extra = parse_extra(args.extra)
        arguments = make_arguments(tool, post_text, author, extra)
        if args.as_json:
            response = None
            if args.dry_run is None:
                response = api.execute(tool, user_id, account['id'], arguments)
            print(json.dumps(json_result('dry-run' if args.dry_run is not None else 'publish',
                                         env_path, account['id'], user_id, author, tool,
                                         arguments, post_text, published=response is not None,
                                         response=response),
                             indent=2, ensure_ascii=False, default=str))
            return 0
        print('Target account:', account['id'], '| user_id:', user_id)
        print('LinkedIn author:', author)
        print('Toolkit version:', tool.get('version'))
        print('Post arguments:\n' + json.dumps(arguments, indent=2, ensure_ascii=False))
        if args.dry_run is not None:
            print('\nDRY RUN — nothing was published.')
            return 0
        print('\nPublishing...')
        response = api.execute(tool, user_id, account['id'], arguments)
        print('Composio confirmed successful execution:')
        print(json.dumps({'data': response.get('data'), 'log_id': response.get('log_id')},
                         indent=2, default=str, ensure_ascii=False))
        print('Check the LinkedIn profile to verify the post is visible.')
        return 0
    except SetupError as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
