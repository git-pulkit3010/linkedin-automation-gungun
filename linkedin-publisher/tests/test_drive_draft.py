#!/usr/bin/env python3
"""Tests for drive_draft.py — the Cowork native Drive connector path."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

BUNDLE = Path(__file__).resolve().parent.parent
SCRIPT = BUNDLE / 'scripts' / 'drive_draft.py'


def load(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location('drivetest_' + name,
                                                  str(BUNDLE / 'scripts' / (name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drive = load('drive_draft')
cli = load('post_linkedin')
stage = load('stage_draft')

DOCX_PARAGRAPHS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:body><w:p><w:r><w:t>Word draft from Drive</w:t></w:r></w:p>'
    '<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p></w:body></w:document>')


def make_docx(path):
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', DOCX_PARAGRAPHS)
    return path


class DriveDraftTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp())
        self.json_env = dict(os.environ)
        self.json_env.pop('COMPOSIO_API_KEY', None)
        self.json_env.pop('COMPOSIO_USER_ID', None)

    def run_cli(self, *argv, stdin=None):
        env = dict(self.json_env)
        env.pop('LINKEDIN_PUBLISHER_ENV_FILE', None)
        process = subprocess.run([sys.executable, str(SCRIPT)] + list(argv),
                                 input=stdin, capture_output=True, text=True, env=env,
                                 cwd=str(self.workspace), timeout=60)
        return process

    # -- staging -------------------------------------------------------------- #

    def test_stages_exported_google_doc_with_name_slug(self):
        download = self.workspace / 'drive-export.txt'
        download.write_text('Launch day is here.\n\n#ProductLaunch body text.\n', encoding='utf-8')
        process = self.run_cli('--file', str(download), '--name', 'Client Launch Post',
                               '--id', '1AbC_dEf', '--link', 'https://docs.google.com/document/d/1AbC_dEf/edit',
                               '--workspace', str(self.workspace), '--json')
        self.assertEqual(process.returncode, 0, process.stderr)
        out = json.loads(process.stdout)
        self.assertEqual(out['mode'], 'import')
        self.assertEqual(out['source'], {'name': 'Client Launch Post', 'id': '1AbC_dEf',
                                        'link': 'https://docs.google.com/document/d/1AbC_dEf/edit'})
        path = Path(out['path'])
        self.assertEqual(path.parent, self.workspace / 'posts')
        self.assertTrue('client-launch-post' in path.name, path.name)
        self.assertTrue(path.name.endswith('.txt'), path.name)
        self.assertEqual(out['char_count'], len(path.read_text(encoding='utf-8')))
        self.assertIn('Launch day is here.', path.read_text(encoding='utf-8'))

    def test_markdown_source_keeps_txt_and_md_extensions(self):
        for name, ext in (('notes.txt', 'txt'), ('draft.md', 'md')):
            download = self.workspace / name
            download.write_text('body text\n', encoding='utf-8')
            process = self.run_cli('--file', str(download), '--workspace', str(self.workspace), '--json')
            self.assertEqual(process.returncode, 0, process.stderr)
            out = json.loads(process.stdout)
            self.assertTrue(Path(out['path']).suffix == '.' + ext, out['path'])

    def test_google_doc_export_is_normalised(self):
        raw = b'line one\r\n\r\n#Tagged\r\n'
        download = self.workspace / 'export.txt'
        download.write_bytes(raw)
        process = self.run_cli('--file', str(download), '--workspace', str(self.workspace), '--json')
        self.assertEqual(process.returncode, 0, process.stderr)
        out = json.loads(process.stdout)
        content = Path(out['path']).read_text(encoding='utf-8')
        self.assertNotIn('\r', content)
        self.assertEqual(content, 'line one\n\n#Tagged\n')

    def test_docx_download_uses_the_same_parser_as_local_files(self):
        download = make_docx(self.workspace / 'raw.docx')
        process = self.run_cli('--file', str(download), '--workspace', str(self.workspace), '--json')
        self.assertEqual(process.returncode, 0, process.stderr)
        out = json.loads(process.stdout)
        content = Path(out['path']).read_text(encoding='utf-8')
        self.assertEqual(content.strip(), 'Word draft from Drive\nSecond paragraph')
        self.assertTrue(Path(out['path']).suffix == '.md')

    def test_stdin_export_is_staged(self):
        process = self.run_cli('--stdin', '--name', 'Piped doc', '--workspace',
                               str(self.workspace), '--json',
                               stdin='Piped draft body\r\n\r\n#Tag\r\n')
        self.assertEqual(process.returncode, 0, process.stderr)
        out = json.loads(process.stdout)
        self.assertIn('Piped draft body', Path(out['path']).read_text(encoding='utf-8'))
        self.assertEqual(out['source'], {'name': 'Piped doc'})
        self.assertEqual(out['char_count'], 23)

    def test_plain_output_prints_only_the_path(self):
        download = self.workspace / 'x.txt'
        download.write_text('quiet path\n', encoding='utf-8')
        process = self.run_cli('--file', str(download), '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 0, process.stderr)
        lines = process.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(Path(lines[0]).is_file())

    def test_second_version_of_the_same_document_does_not_overwrite(self):
        for body in ('first text', 'second text'):
            download = self.workspace / 'same.txt'
            download.write_text(body + '\n', encoding='utf-8')
            self.run_cli('--file', str(download), '--name', 'Same Doc',
                         '--workspace', str(self.workspace))
        names = sorted(p.name for p in (self.workspace / 'posts').iterdir())
        self.assertEqual(names, ['2026-11-12-same-doc-2.txt', '2026-11-12-same-doc.txt'], names)

    def test_needs_no_composio_credentials_and_no_network(self):
        """Staging a Drive draft must work with no key and no connectivity."""
        download = self.workspace / 'offline.txt'
        download.write_text('staged without Composio\n', encoding='utf-8')
        env = {k: v for k, v in os.environ.items()
               if k not in {'COMPOSIO_API_KEY', 'COMPOSIO_USER_ID',
                            'COMPOSIO_CONNECTED_ACCOUNT_ID', 'GOOGLEDRIVE_CONNECTED_ACCOUNT_ID',
                            'LINKEDIN_AUTHOR_URN', 'LINKEDIN_PUBLISHER_ENV_FILE'}}
        process = subprocess.run([sys.executable, str(SCRIPT), '--file', str(download),
                                  '--workspace', str(self.workspace), '--json'],
                                 capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        out = json.loads(process.stdout)
        self.assertTrue(Path(out['path']).is_file())

    # -- guards --------------------------------------------------------------- #

    def test_missing_download_is_rejected(self):
        process = self.run_cli('--file', str(self.workspace / 'nope.txt'),
                               '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 1)
        self.assertIn('Drive download not found', process.stderr)
        self.assertEqual(process.stdout, '')

    def test_unsupported_download_type_is_rejected(self):
        download = self.workspace / 'sheet.csv'
        download.write_text('a,b\n', encoding='utf-8')
        process = self.run_cli('--file', str(download), '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 1)
        self.assertIn('Unsupported Drive file type: .csv', process.stderr)

    def test_empty_export_is_rejected(self):
        download = self.workspace / 'empty.txt'
        download.write_text('   \n\n', encoding='utf-8')
        process = self.run_cli('--file', str(download), '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 1)
        self.assertIn('contains no text', process.stderr)

    def test_empty_stdin_is_rejected(self):
        process = self.run_cli('--stdin', '--workspace', str(self.workspace), stdin='  \n')
        self.assertEqual(process.returncode, 1)
        self.assertIn('No text was piped', process.stderr)

    def test_workspace_is_required(self):
        process = self.run_cli('--file', 'x.txt')
        self.assertEqual(process.returncode, 2)
        self.assertIn('--workspace', process.stderr)

    def test_a_source_is_required(self):
        process = self.run_cli('--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 2)
        self.assertIn('--file', process.stderr)

    def test_file_and_stdin_are_mutually_exclusive(self):
        process = self.run_cli('--file', 'x.txt', '--stdin', '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 2)

    def test_bad_drive_id_is_rejected(self):
        download = self.workspace / 'ok.txt'
        download.write_text('body\n', encoding='utf-8')
        process = self.run_cli('--file', str(download), '--id', 'not a valid id!',
                               '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 1)
        self.assertIn('--id must be a Google Drive file ID', process.stderr)

    def test_blank_name_and_non_https_link_are_rejected(self):
        download = self.workspace / 'ok.txt'
        download.write_text('body\n', encoding='utf-8')
        for extra, message in ((['--name', '  '], '--name must not be blank'),
                               (['--link', 'http://insecure.example/x'], '--link must be an HTTPS')):
            process = self.run_cli('--file', str(download), '--workspace', str(self.workspace), *extra)
            self.assertEqual(process.returncode, 1, process.stderr)
            self.assertIn(message, process.stderr)

    def test_broken_docx_is_rejected_cleanly(self):
        download = self.workspace / 'broken.docx'
        download.write_bytes(b'not a zip')
        process = self.run_cli('--file', str(download), '--workspace', str(self.workspace))
        self.assertEqual(process.returncode, 1)
        self.assertIn('Cannot read the Drive download', process.stderr)

    # -- units ---------------------------------------------------------------- #

    def test_stage_extension_follows_the_source_name(self):
        self.assertEqual(drive.stage_extension('Client Launch Post.md'), 'md')
        self.assertEqual(drive.stage_extension('export.txt'), 'txt')
        self.assertEqual(drive.stage_extension('Launch (v2).DOCX'), 'md')
        self.assertEqual(drive.stage_extension(None), 'md')

    def test_stdin_decoder_matches_read_post_bytes(self):
        raw = b'parity\r\nsecond\r\n'
        self.assertEqual(raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n'),
                         cli.read_post_bytes(raw, '.txt'))

    def test_main_prints_error_not_traceback(self):
        argv = sys.argv
        sys.argv = ['drive_draft.py', '--file', '/definitely/missing.txt',
                    '--workspace', str(self.workspace)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = drive.main()
        sys.argv = argv
        self.assertEqual(code, 1)
        self.assertTrue(err.getvalue().startswith('ERROR: '), err.getvalue())
        self.assertNotIn('Traceback', err.getvalue())


if __name__ == '__main__':
    unittest.main()
