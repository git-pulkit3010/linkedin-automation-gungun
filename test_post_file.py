"""Offline checks for post content loaded from local documents."""

import contextlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import post_linkedin


class PostFileTests(unittest.TestCase):
    def test_utf8_text_and_markdown_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ('.txt', '.md'):
                with self.subTest(suffix=suffix):
                    path = Path(directory) / ('draft' + suffix)
                    path.write_text('Hello 🌍\n\nSecond line\n', encoding='utf-8')
                    self.assertEqual(post_linkedin.read_post_file(path),
                                     'Hello 🌍\n\nSecond line\n')

    def test_docx_extracts_paragraphs_and_table_cells_in_order(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/'
               'wordprocessingml/2006/main"><w:body>'
               '<w:p><w:r><w:t>Hello </w:t></w:r>'
               '<w:hyperlink><w:r><w:t>world</w:t></w:r></w:hyperlink></w:p>'
               '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r>'
               '</w:p></w:tc></w:tr></w:tbl>'
               '<w:p><w:r><w:t>Last</w:t><w:tab/><w:t>line</w:t>'
               '</w:r></w:p></w:body></w:document>')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.docx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('word/document.xml', xml)
            self.assertEqual(post_linkedin.read_post_file(path),
                             'Hello world\nCell\nLast\tline')

    def test_invalid_files_fail_with_setup_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {'missing.md': None, 'unsupported.pdf': b'hello',
                     'empty.txt': b'  \n', 'binary.md': b'\xff',
                     'broken.docx': b'not a docx'}
            for filename, data in cases.items():
                with self.subTest(filename=filename):
                    path = root / filename
                    if data is not None:
                        path.write_bytes(data)
                    with self.assertRaises(post_linkedin.SetupError):
                        post_linkedin.read_post_file(path)


class CommandLineFileTests(unittest.TestCase):
    def run_main(self, *args):
        output = io.StringIO()
        error = io.StringIO()
        calls = []

        class FakeAPI:
            def __init__(self, key):
                pass

            def linkedin_tools(self):
                return [{'slug': post_linkedin.POST_SLUG}]

            def tool(self, slug):
                return {'slug': slug, 'version': '20261026_00',
                        'input_parameters': {'author': {}, 'commentary': {}}}

            def execute(self, tool, user_id, account_id, arguments):
                calls.append(arguments)
                return {'successful': True, 'data': {'id': 'example'}, 'log_id': 'test'}

        with patch.object(post_linkedin, 'ComposioAPI', FakeAPI), \
             patch.object(post_linkedin, 'active_linkedin_account',
                          return_value={'id': 'account'}), \
             patch.object(post_linkedin, 'get_author',
                          return_value='urn:li:person:test'), \
             patch.object(post_linkedin.os, 'getenv', return_value='test-user'), \
             patch.object(post_linkedin.sys, 'argv', ['post_linkedin.py', *args]), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = post_linkedin.main()
        return result, output.getvalue(), error.getvalue(), calls

    def test_dry_run_uses_file_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.md'
            path.write_text('From **file**\n', encoding='utf-8')
            code, stdout, stderr, calls = self.run_main('--dry-run', '--file', str(path))
        self.assertEqual(code, 0, stderr)
        self.assertIn('From **file**', stdout)
        self.assertIn('DRY RUN', stdout)
        self.assertEqual(calls, [])

    def test_publish_uses_file_contents_as_post_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.txt'
            path.write_text('Approved file content', encoding='utf-8')
            code, _, stderr, calls = self.run_main('--publish', '--file', str(path))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(calls, [{'author': 'urn:li:person:test',
                                  'commentary': 'Approved file content'}])

    def test_text_and_file_together_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.txt'
            path.write_text('File content', encoding='utf-8')
            code, _, stderr, calls = self.run_main('--dry-run', 'Text', '--file', str(path))
        self.assertNotEqual(code, 0)
        self.assertIn('either', stderr.lower())
        self.assertEqual(calls, [])

    def test_existing_text_argument_still_works(self):
        code, stdout, stderr, calls = self.run_main('--dry-run', 'Inline text')
        self.assertEqual(code, 0, stderr)
        self.assertIn('Inline text', stdout)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
