#!/usr/bin/env python3
"""Find a Google Drive draft or import one into posts/ for LinkedIn preview.

Uses the same Composio API key and user as post_linkedin.py. Google Drive must
be connected separately to that user. This script never publishes a post.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

SCRIPT_DIR = Path(__file__).resolve().parent
DOC_MIME = 'application/vnd.google-apps.document'
SUPPORTED = {DOC_MIME, 'text/plain', 'text/markdown',
             'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
DRIVE_API = 'https://www.googleapis.com/drive/v3/files'


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, str(SCRIPT_DIR / (name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def drive_account(api, user_id):
    if not user_id:
        raise ValueError('COMPOSIO_USER_ID is missing from .env.')
    matches = [a for a in api.accounts()
               if (a.get('toolkit') or {}).get('slug', '').lower() == 'googledrive'
               and a.get('user_id') == user_id and a.get('status') == 'ACTIVE'
               and not a.get('is_disabled', False)]
    selected = os.getenv('GOOGLEDRIVE_CONNECTED_ACCOUNT_ID', '').strip()
    if selected:
        matches = [a for a in matches if a.get('id') == selected]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError('No ACTIVE Google Drive connection matches COMPOSIO_USER_ID'
                         + (' and GOOGLEDRIVE_CONNECTED_ACCOUNT_ID' if selected else '')
                         + '. Connect Google Drive in the same Composio project and user.')
    raise ValueError('Multiple ACTIVE Google Drive connections. Set '
                     'GOOGLEDRIVE_CONNECTED_ACCOUNT_ID to one of: '
                     + ', '.join(a['id'] for a in matches))


def proxy(api, user_id, account_id, endpoint, parameters=()):
    result = api.request('POST', '/tools/execute/proxy', body={
        'connected_account_id': account_id, 'user_id': user_id,
        'endpoint': endpoint, 'method': 'GET',
        'parameters': [{'name': key, 'value': value, 'type': 'query'}
                       for key, value in parameters]})
    status = result.get('status')
    if not isinstance(status, int) or not 200 <= status < 300:
        detail = result.get('data')
        raise ValueError('Google Drive request failed (HTTP {}): {}'.format(
            status, json.dumps(detail, ensure_ascii=False, default=str)[:600]))
    return result


def search(api, user_id, account_id, phrase):
    phrase = phrase.strip()
    if not phrase:
        raise ValueError('--search needs a non-empty filename phrase.')
    escaped = phrase.replace('\\', '\\\\').replace("'", "\\'")
    query = "trashed = false and name contains '{}'".format(escaped)
    files, token = [], None
    for _ in range(10):
        params = [('q', query), ('fields', 'nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)'),
                  ('pageSize', '100'), ('orderBy', 'modifiedTime desc')]
        if token:
            params.append(('pageToken', token))
        data = proxy(api, user_id, account_id, DRIVE_API, params).get('data')
        if not isinstance(data, dict) or not isinstance(data.get('files'), list):
            raise ValueError('Unexpected Google Drive search response.')
        files.extend(f for f in data['files'] if f.get('mimeType') in SUPPORTED)
        next_token = data.get('nextPageToken')
        if not next_token or next_token == token:
            return files
        token = next_token
    raise ValueError('Google Drive search exceeded 10 pages. Use a narrower filename phrase.')


def file_id_from_url(value):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname not in {'drive.google.com', 'docs.google.com'}:
        raise ValueError('--url must be a Google Drive or Google Docs HTTPS link.')
    match = re.search(r'/d/([A-Za-z0-9_-]+)(?:/|$)', parsed.path)
    file_id = match.group(1) if match else parse_qs(parsed.query).get('id', [''])[0]
    if not re.fullmatch(r'[A-Za-z0-9_-]+', file_id):
        raise ValueError('Could not find a file ID in the Google link. Use --file-id instead.')
    return file_id


def metadata(api, user_id, account_id, file_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', file_id):
        raise ValueError('Invalid Google Drive file ID.')
    data = proxy(api, user_id, account_id, DRIVE_API + '/' + quote(file_id, safe=''),
                 [('fields', 'id,name,mimeType,modifiedTime,webViewLink,trashed')]).get('data')
    if not isinstance(data, dict) or data.get('id') != file_id:
        raise ValueError('Unexpected Google Drive file metadata.')
    if data.get('trashed'):
        raise ValueError('The selected Google Drive file is in the trash.')
    if data.get('mimeType') not in SUPPORTED:
        raise ValueError('Unsupported Google Drive file type. Use a Google Doc, .txt, .md, or .docx.')
    return data


def download_bytes(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host.endswith('.amazonaws.com') or
                                        host == 'amazonaws.com' or
                                        host.endswith('.composio.dev')):
        raise ValueError('Composio returned an unexpected download host.')
    try:
        with urlopen(Request(url), timeout=30) as response:
            if urlparse(response.geturl()).hostname != host:
                raise ValueError('Composio download redirected to an unexpected host.')
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (HTTPError, URLError, OSError) as exc:
        raise ValueError('Could not download the Google Drive file: {}'.format(exc)) from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError('Google Drive draft exceeds the 10 MB import limit.')
    return data


def import_text(api, user_id, account_id, item, cli):
    file_id, mime = item['id'], item['mimeType']
    endpoint = DRIVE_API + '/' + quote(file_id, safe='')
    if mime == DOC_MIME:
        result = proxy(api, user_id, account_id, endpoint + '/export',
                       [('mimeType', 'text/plain')])
        suffix = '.txt'
    else:
        result = proxy(api, user_id, account_id, endpoint, [('alt', 'media')])
        suffix = '.docx' if mime.endswith('wordprocessingml.document') else '.txt'
    binary = result.get('binary_data') or result.get('binaryData')
    if isinstance(binary, dict) and binary.get('url'):
        data = download_bytes(binary['url'])
        try:
            text = cli.read_post_bytes(data, suffix)
        except (UnicodeError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError('Cannot read the downloaded Google Drive draft: {}'.format(exc)) from exc
    elif isinstance(result.get('data'), str) and suffix == '.txt':
        text = result['data']
    else:
        raise ValueError('Google Drive returned no downloadable file content.')
    if not text.strip():
        raise ValueError('The Google Drive draft contains no text.')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--search', metavar='PHRASE', help='Find supported drafts by filename')
    source.add_argument('--file-id', metavar='ID', help='Import this exact Google Drive file ID')
    source.add_argument('--url', metavar='LINK', help='Import from a Google Drive/Docs link')
    parser.add_argument('--workspace', metavar='DIR', help='Workspace for posts/ (required for import)')
    parser.add_argument('--env-file', metavar='PATH', help='Use this .env file')
    parser.add_argument('--json', action='store_true', help='Print one JSON object')
    args = parser.parse_args()
    cli = load_script('post_linkedin')
    try:
        if not args.search and not args.workspace:
            raise ValueError('--workspace is required when importing a draft.')
        env_path, _ = cli.resolve_env_file(args.env_file)
        if env_path:
            cli.apply_env_file(env_path)
        api = cli.ComposioAPI(os.getenv('COMPOSIO_API_KEY'))
        user_id = os.getenv('COMPOSIO_USER_ID', '').strip()
        account_id = drive_account(api, user_id)['id']
        if args.search:
            files = search(api, user_id, account_id, args.search)
            output = {'mode': 'search', 'files': files, 'account_id': account_id}
        else:
            file_id = args.file_id or file_id_from_url(args.url)
            item = metadata(api, user_id, account_id, file_id)
            body = import_text(api, user_id, account_id, item, cli)
            stage = load_script('stage_draft')
            path = stage.write_draft(args.workspace, body, slug=Path(item['name']).stem)
            output = {'mode': 'import', 'source': item, 'path': str(path),
                      'char_count': len(path.read_text(encoding='utf-8')),
                      'account_id': account_id}
        if args.json:
            print(json.dumps(output, ensure_ascii=False))
        elif args.search:
            for item in files:
                print('{}\t{}\t{}\t{}'.format(item['id'], item['name'],
                                                  item.get('modifiedTime', ''),
                                                  item.get('webViewLink', '')))
        else:
            print(output['path'])
        return 0
    except (ValueError, OSError, UnicodeError, cli.SetupError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
