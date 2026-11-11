"""Offline checks for Google Drive discovery and draft import."""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('drive_draft', str(SCRIPTS / 'drive_draft.py'))
DRIVE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DRIVE)


class FakeAPI:
    def __init__(self, key='key'):
        self.calls = []

    def accounts(self):
        return [{'id': 'drive-1', 'user_id': 'user-1', 'status': 'ACTIVE',
                 'toolkit': {'slug': 'googledrive'}}]

    def request(self, method, path, *, body=None, params=None):
        self.calls.append((method, path, body))
        endpoint = body['endpoint']
        parameters = {p['name']: p['value'] for p in body['parameters']}
        if endpoint == DRIVE.DRIVE_API:
            return {'status': 200, 'data': {'files': [
                {'id': 'doc-1', 'name': 'Draft', 'mimeType': DRIVE.DOC_MIME},
                {'id': 'sheet-1', 'name': 'Sheet',
                 'mimeType': 'application/vnd.google-apps.spreadsheet'}]}}
        if endpoint.endswith('/doc-1/export'):
            assert parameters['mimeType'] == 'text/plain'
            return {'status': 200, 'binary_data': {'url':
                    'https://bucket.s3.amazonaws.com/draft?signature=secret'}}
        if endpoint.endswith('/doc-1'):
            return {'status': 200, 'data': {'id': 'doc-1', 'name': 'Draft',
                    'mimeType': DRIVE.DOC_MIME, 'trashed': False}}
        raise AssertionError(endpoint)


class DriveDraftTests(unittest.TestCase):
    def test_search_filters_unsupported_files_and_escapes_query(self):
        api = FakeAPI()
        files = DRIVE.search(api, 'user-1', 'drive-1', "Ann's draft")
        self.assertEqual([f['id'] for f in files], ['doc-1'])
        params = {p['name']: p['value'] for p in api.calls[0][2]['parameters']}
        self.assertIn("Ann\\'s draft", params['q'])

    def test_drive_url_extracts_id_and_rejects_other_hosts(self):
        self.assertEqual(DRIVE.file_id_from_url(
            'https://docs.google.com/document/d/doc-1/edit'), 'doc-1')
        self.assertEqual(DRIVE.file_id_from_url(
            'https://drive.google.com/open?id=doc-1'), 'doc-1')
        with self.assertRaises(ValueError):
            DRIVE.file_id_from_url('https://docs.google.com.evil.test/document/d/doc-1/edit')

    def test_import_stages_exact_document_text_and_never_posts(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / '.env'
            env.write_text('COMPOSIO_API_KEY=key\nCOMPOSIO_USER_ID=user-1\n', encoding='utf-8')
            argv = ['drive_draft.py', '--file-id', 'doc-1', '--workspace', directory,
                    '--env-file', str(env), '--json']
            out = io.StringIO()
            with patch.object(DRIVE.sys, 'argv', argv), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch.object(DRIVE, 'load_script', side_effect=lambda name:
                              _fake_cli(api) if name == 'post_linkedin' else _real_stage()), \
                 patch.object(DRIVE, 'download_bytes', return_value=b'Exact body\n\n#Tag'), \
                 contextlib.redirect_stdout(out):
                self.assertEqual(DRIVE.main(), 0)
            result = json.loads(out.getvalue())
            self.assertEqual(Path(result['path']).read_text(encoding='utf-8'),
                             'Exact body\n\n#Tag\n')
            self.assertEqual(result['source']['id'], 'doc-1')
            self.assertEqual(result['mode'], 'import')
            self.assertEqual(len(api.calls), 2)

    def test_docx_content_uses_existing_parser(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('word/document.xml',
                             '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                             'wordprocessingml/2006/main"><w:body><w:p><w:r>'
                             '<w:t>Word draft</w:t></w:r></w:p></w:body></w:document>')
        cli = _fake_cli(FakeAPI())
        self.assertEqual(cli.read_post_bytes(buffer.getvalue(), '.docx'), 'Word draft')

    def test_stored_text_file_is_downloaded_as_media(self):
        api = FakeAPI()
        item = {'id': 'text-1', 'name': 'draft.md', 'mimeType': 'text/markdown'}
        response = {'status': 200, 'binary_data': {'url':
                    'https://bucket.s3.amazonaws.com/draft?signature=secret'}}
        with patch.object(DRIVE, 'proxy', return_value=response) as proxied, \
             patch.object(DRIVE, 'download_bytes', return_value=b'From Drive\n'):
            text = DRIVE.import_text(api, 'user-1', 'drive-1', item, _real_cli())
        self.assertEqual(text, 'From Drive\n')
        self.assertEqual(proxied.call_args.args[3], DRIVE.DRIVE_API + '/text-1')
        self.assertIn(('alt', 'media'), proxied.call_args.args[4])

    def test_download_rejects_untrusted_host(self):
        with self.assertRaisesRegex(ValueError, 'unexpected download host'):
            DRIVE.download_bytes('https://example.org/private')

    def test_multiple_drive_accounts_require_explicit_selection(self):
        api = FakeAPI()
        api.accounts = lambda: [
            {'id': name, 'user_id': 'user-1', 'status': 'ACTIVE',
             'toolkit': {'slug': 'googledrive'}} for name in ('a', 'b')]
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'Multiple ACTIVE'):
                DRIVE.drive_account(api, 'user-1')
            os.environ['GOOGLEDRIVE_CONNECTED_ACCOUNT_ID'] = 'b'
            self.assertEqual(DRIVE.drive_account(api, 'user-1')['id'], 'b')


def _fake_cli(api):
    module = _real_cli()
    module.ComposioAPI = lambda key: api
    return module


def _real_cli():
    spec = importlib.util.spec_from_file_location('drive_test_post',
                                                  str(SCRIPTS / 'post_linkedin.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_stage():
    spec = importlib.util.spec_from_file_location('drive_test_stage',
                                                  str(SCRIPTS / 'stage_draft.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    unittest.main()
