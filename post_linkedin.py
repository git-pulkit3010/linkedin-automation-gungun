#!/usr/bin/env python3
"""Inspect or publish a LinkedIn text post with Composio's v3.1 REST API.

Requires: python -m pip install requests python-dotenv
.env: COMPOSIO_API_KEY and COMPOSIO_USER_ID
Optional: COMPOSIO_CONNECTED_ACCOUNT_ID, LINKEDIN_AUTHOR_URN

Read-only:
    python post_linkedin.py --inspect
    python post_linkedin.py --dry-run 'Hello LinkedIn'
    python post_linkedin.py --dry-run --file draft.docx
Publish (real post):
    python post_linkedin.py --publish 'Hello LinkedIn'
    python post_linkedin.py --publish --file draft.md
"""

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name('.env'))
API_ROOT = 'https://backend.composio.dev/api/v3.1'
POST_SLUG = 'LINKEDIN_CREATE_LINKED_IN_POST'
PROFILE_SLUG = 'LINKEDIN_GET_MY_INFO'


class SetupError(Exception):
    pass


def read_post_file(path):
    """Read the post body from a UTF-8 document or Word document."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {'.txt', '.md', '.docx'}:
        raise SetupError('Unsupported post file type: ' + suffix + '. Use .txt, .md, or .docx.')
    try:
        if suffix == '.docx':
            with zipfile.ZipFile(path) as archive:
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
            content = '\n'.join(paragraphs)
        else:
            content = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError, zipfile.BadZipFile, KeyError,
            ElementTree.ParseError) as exc:
        raise SetupError(f'Cannot read post file {path}: {exc}') from exc
    if not content.strip():
        raise SetupError(f'Post file {path} contains no text.')
    return content


class ComposioAPI:
    def __init__(self, key):
        if not key:
            raise SetupError('COMPOSIO_API_KEY is missing from .env')
        self.session = requests.Session()
        self.session.headers.update({'x-api-key': key, 'Accept': 'application/json'})

    def request(self, method, path, *, params=None, body=None):
        try:
            response = self.session.request(
                method, API_ROOT + path, params=params, json=body, timeout=30
            )
        except requests.RequestException as exc:
            raise SetupError(f'Network error contacting Composio: {exc}') from exc
        try:
            result = response.json()
        except ValueError:
            result = {'message': response.text[:1000]}
        if not response.ok:
            detail = json.dumps(result, ensure_ascii=False, default=str)[:1800]
            hint = (' (Check COMPOSIO_API_KEY and project.)' if response.status_code in (401, 403)
                    else '')
            raise SetupError(f'Composio HTTP {response.status_code}: {detail}{hint}')
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
    args = parser.parse_args()
    try:
        if args.inspect and args.file:
            raise SetupError('--file can only be used with --dry-run or --publish')
        inline_text = args.dry_run if args.dry_run is not None else args.publish
        if not args.inspect:
            if args.file and inline_text:
                raise SetupError('Supply either inline text or --file, not both.')
            if not args.file and not inline_text:
                raise SetupError('Supply either inline text or --file.')
            post_text = read_post_file(args.file) if args.file else inline_text
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
        user_id = os.getenv('COMPOSIO_USER_ID', '').strip()
        account = active_linkedin_account(api, user_id)
        author = get_author(api, user_id, account['id'])
        try:
            extra = json.loads(args.extra)
        except json.JSONDecodeError as exc:
            raise SetupError('--extra is invalid JSON: ' + str(exc)) from exc
        if not isinstance(extra, dict):
            raise SetupError('--extra must be a JSON object')
        arguments = make_arguments(tool, post_text, author, extra)
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
