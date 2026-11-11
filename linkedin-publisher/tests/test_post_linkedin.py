#!/usr/bin/env python3
"""Offline unittest suite for the linkedin-publisher skill bundle.

No network access and no credentials: every Composio call is replaced by a stub and
each CLI run happens inside a throwaway directory with a clean environment.
From the repository root:

    python3 -m unittest discover -s linkedin-publisher/tests -t linkedin-publisher/tests -v
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = BUNDLE_ROOT / 'scripts'
REPO_ROOT = BUNDLE_ROOT.parent


def load_script(name, filename):
    """Load a bundle script by path — the folder name has a hyphen, so it is not a package."""
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load_script('bundle_post_linkedin', 'post_linkedin.py')
STAGE = load_script('bundle_stage_draft', 'stage_draft.py')
DOCTOR = load_script('bundle_doctor', 'doctor.py')

DOCX_XML = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>Hello </w:t></w:r>'
            '<w:hyperlink><w:r><w:t>world</w:t></w:r></w:hyperlink></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r>'
            '</w:p></w:tc></w:tr></w:tbl>'
            '<w:p><w:r><w:t>Last</w:t><w:tab/><w:t>line</w:t>'
            '</w:r></w:p></w:body></w:document>')


def write_docx(directory, name='draft.docx'):
    path = Path(directory) / name
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', DOCX_XML)
    return path


class FakeResponse:
    """Stand-in for the object returned by urllib.request.urlopen."""

    def __init__(self, payload, status=200):
        if isinstance(payload, dict):
            self.body = json.dumps(payload).encode('utf-8')
        elif isinstance(payload, str):
            self.body = payload.encode('utf-8')
        else:
            self.body = payload or b''
        self.status = status

    def getcode(self):
        return self.status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeAPI:
    """Replaces ComposioAPI: records execute calls, publishes nothing."""

    instances = []

    def __init__(self, key):
        if not key:
            raise CLI.SetupError('COMPOSIO_API_KEY is missing from .env')
        self.key = key
        self.calls = []
        FakeAPI.instances.append(self)

    def linkedin_tools(self):
        return [{'slug': CLI.POST_SLUG}, {'slug': CLI.PROFILE_SLUG}]

    def tool(self, slug):
        return {'slug': slug, 'version': '20261026_00',
                'input_parameters': {'author': {}, 'commentary': {}, 'visibility': {}}}

    def execute(self, tool, user_id, account_id, arguments):
        self.calls.append({'tool': tool.get('slug'), 'account_id': account_id,
                          'user_id': user_id, 'arguments': arguments})
        return {'successful': True, 'data': {'id': 'post-1'}, 'log_id': 'log-1'}


def run_cli(args, env=None, make_env_file=True, skill_root=None):
    """Run CLI.main() in an isolated cwd and environment; capture stdout/stderr."""
    output, error = io.StringIO(), io.StringIO()
    FakeAPI.instances = []
    stack = contextlib.ExitStack()
    try:
        home = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        sandbox = home / 'workspace' / 'inner'
        sandbox.mkdir(parents=True)
        if make_env_file:
            (home / 'workspace' / '.env').write_text(
                "COMPOSIO_API_KEY='file-api-key'\nCOMPOSIO_USER_ID=file-user\n", encoding='utf-8')
        patches = [patch.object(CLI, 'ComposioAPI', FakeAPI),
                   patch.dict(os.environ, env or {}, clear=True),
                   patch.object(CLI.sys, 'argv', ['post_linkedin.py'] + [str(a) for a in args]),
                   patch.object(CLI, 'active_linkedin_account',
                                lambda api, user_id: {'id': 'account-1'}),
                   patch.object(CLI, 'get_author',
                                lambda api, user_id, account_id: 'urn:li:person:test')]
        if skill_root is not None:
            patches.append(patch.object(CLI, 'SKILL_ROOT', Path(skill_root)))
        for item in patches:
            stack.enter_context(item)
        stack.enter_context(contextlib.redirect_stdout(output))
        stack.enter_context(contextlib.redirect_stderr(error))
        previous = os.getcwd()
        os.chdir(str(sandbox))
        try:
            code = CLI.main()
        finally:
            os.chdir(previous)
    finally:
        stack.close()
    api = FakeAPI.instances[0] if FakeAPI.instances else None
    return (code, output.getvalue(), error.getvalue(),
            api.calls if api else [], api.key if api else None)


class EnvironmentParserTests(unittest.TestCase):
    def parse(self, text):
        return CLI.parse_env_text(text)

    def test_plain_and_exported_assignments(self):
        self.assertEqual(self.parse('A=one\nexport B=two\n'), {'A': 'one', 'B': 'two'})

    def test_quotes_are_stripped_and_inner_content_kept(self):
        self.assertEqual(self.parse('A="double quoted"\nB=\'single quoted\'\nC="has = inside"\n'),
                         {'A': 'double quoted', 'B': 'single quoted', 'C': 'has = inside'})

    def test_comments_and_blank_lines_are_ignored(self):
        self.assertEqual(self.parse('\n# a comment\n   \nA=one\n  # indented comment\nB=two\n'),
                         {'A': 'one', 'B': 'two'})

    def test_inline_comments_only_apply_to_unquoted_values(self):
        values = self.parse('A=one   # trailing comment\nB="two # not a comment"\nC=hash#inside\n')
        self.assertEqual(values['A'], 'one')
        self.assertEqual(values['B'], 'two # not a comment')
        self.assertEqual(values['C'], 'hash#inside')

    def test_empty_values_and_lines_without_equals(self):
        values = self.parse('A=\njust-a-word\n   \n')
        self.assertEqual(values, {'A': ''})

    def test_windows_line_endings(self):
        self.assertEqual(self.parse('A=one\r\nB="two"\r\n'), {'A': 'one', 'B': 'two'})

    def test_load_env_file_from_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('COMPOSIO_API_KEY="k-123"  # key\n', encoding='utf-8')
            self.assertEqual(CLI.load_env_file(path), {'COMPOSIO_API_KEY': 'k-123'})

    def test_load_env_file_missing_raises_setup_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CLI.SetupError):
                CLI.load_env_file(Path(directory) / 'absent.env')


class EnvDiscoveryTests(unittest.TestCase):
    def make_tree(self, root):
        skill = Path(root) / 'skill'
        cwd = Path(root) / 'ws' / 'here'
        cwd.mkdir(parents=True)
        return skill, cwd

    def touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('A=1\n', encoding='utf-8')
        return path

    def test_skill_root_beats_cwd_and_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            expected = self.touch(skill / '.env')
            self.touch(cwd / '.env')
            self.touch(cwd.parent / '.env')
            path, source = CLI.resolve_env_file(None, cwd=cwd, skill_root=skill)
            self.assertEqual((path, source), (expected, 'skill root'))

    def test_cwd_beats_parent_when_skill_root_has_no_env(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            self.touch(cwd / '.env')
            expected = self.touch(cwd.parent / '.env')
            path, source = CLI.resolve_env_file(None, cwd=cwd, skill_root=skill)
            self.assertEqual((path, source), (cwd / '.env', 'current directory'))
            self.assertTrue(expected.is_file())

    def test_parent_directory_is_the_last_resort(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            expected = self.touch(cwd.parent / '.env')
            path, source = CLI.resolve_env_file(None, cwd=cwd, skill_root=skill)
            self.assertEqual((path, source), (expected, 'parent directory'))

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            self.assertEqual(CLI.resolve_env_file(None, cwd=cwd, skill_root=skill), (None, 'none'))

    def test_explicit_file_is_used_and_must_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            self.touch(skill / '.env')
            chosen = self.touch(Path(directory) / 'custom.env')
            path, source = CLI.resolve_env_file(str(chosen), cwd=cwd, skill_root=skill)
            self.assertEqual((path, source), (chosen, 'flag'))
            with self.assertRaises(CLI.SetupError) as caught:
                CLI.resolve_env_file(str(Path(directory) / 'nope.env'), cwd=cwd, skill_root=skill)
            self.assertIn('Env file not found', str(caught.exception))

    def test_environment_variable_override(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            self.touch(skill / '.env')
            chosen = self.touch(Path(directory) / 'override.env')
            with patch.dict(os.environ, {'LINKEDIN_PUBLISHER_ENV_FILE': str(chosen)}):
                path, source = CLI.resolve_env_file(None, cwd=cwd, skill_root=skill)
            self.assertEqual((path, source), (chosen, 'LINKEDIN_PUBLISHER_ENV_FILE'))

    def test_environment_variable_override_must_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            skill, cwd = self.make_tree(directory)
            with patch.dict(os.environ,
                            {'LINKEDIN_PUBLISHER_ENV_FILE': str(Path(directory) / 'x')}):
                with self.assertRaises(CLI.SetupError):
                    CLI.resolve_env_file(None, cwd=cwd, skill_root=skill)

    def test_real_environment_beats_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('COMPOSIO_API_KEY=from-file\n', encoding='utf-8')
            with patch.dict(os.environ, {'COMPOSIO_API_KEY': 'from-real-env'}):
                CLI.apply_env_file(path)
                self.assertEqual(os.environ['COMPOSIO_API_KEY'], 'from-real-env')

    def test_file_fills_in_what_the_environment_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('COMPOSIO_USER_ID=from-file\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                CLI.apply_env_file(path)
                self.assertEqual(os.environ['COMPOSIO_USER_ID'], 'from-file')


class ReadPostFileTests(unittest.TestCase):
    def test_txt_and_md_are_returned_verbatim(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ('.txt', '.md'):
                with self.subTest(suffix=suffix):
                    path = Path(directory) / ('draft' + suffix)
                    path.write_text('Hello 🌍\n\nSecond paragraph\n', encoding='utf-8')
                    self.assertEqual(CLI.read_post_file(path), 'Hello 🌍\n\nSecond paragraph\n')

    def test_docx_paragraphs_and_tables_in_document_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_docx(directory)
            self.assertEqual(CLI.read_post_file(path), 'Hello world\nCell\nLast\tline')

    def test_failure_cases(self):
        cases = {'missing.md': None, 'unsupported.pdf': b'hello', 'empty.txt': b'  \n',
                 'binary.md': b'\xff', 'broken.docx': b'not a docx'}
        with tempfile.TemporaryDirectory() as directory:
            for name, data in cases.items():
                with self.subTest(name=name):
                    path = Path(directory) / name
                    if data is not None:
                        path.write_bytes(data)
                    with self.assertRaises(CLI.SetupError):
                        CLI.read_post_file(path)

    def test_unsupported_type_names_the_allowed_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'notes.rtf'
            path.write_text('body', encoding='utf-8')
            with self.assertRaises(CLI.SetupError) as caught:
                CLI.read_post_file(path)
            self.assertIn('.txt, .md, or .docx', str(caught.exception))


class HashtagAndLengthTests(unittest.TestCase):
    def test_hashtags_in_order_without_duplicates(self):
        text = 'Intro\n\n#AI #Leadership #ai again\n\n#OneWord_2\n'
        self.assertEqual(CLI.extract_hashtags(text), ['#AI', '#Leadership', '#OneWord_2'])

    def test_no_hashtags_is_an_empty_list(self):
        self.assertEqual(CLI.extract_hashtags('plain text'), [])

    def test_check_length_passes_within_limit(self):
        self.assertEqual(CLI.check_length('x' * 10, 3000), 10)

    def test_check_length_reports_the_overflow(self):
        with self.assertRaises(CLI.SetupError) as caught:
            CLI.check_length('x' * 3010, 3000)
        message = str(caught.exception)
        self.assertIn('3010 characters', message)
        self.assertIn('10 over the 3000-character limit', message)
        self.assertIn('Shorten', message)


class AccountAndAuthorTests(unittest.TestCase):
    class StubAPI:
        def __init__(self, accounts):
            self._accounts = accounts

        def accounts(self):
            return self._accounts

    def linkedin(self, account_id, status='ACTIVE', user_id='gungun', **extra):
        record = {'id': account_id, 'user_id': user_id, 'status': status,
                  'toolkit': {'slug': 'linkedin'}}
        record.update(extra)
        return record

    def test_single_active_account_is_selected(self):
        api = self.StubAPI([self.linkedin('acc-1'), self.linkedin('acc-2', status='INACTIVE'),
                            {'id': 'x', 'user_id': 'gungun', 'status': 'ACTIVE',
                             'toolkit': {'slug': 'github'}}])
        self.assertEqual(CLI.active_linkedin_account(api, 'gungun')['id'], 'acc-1')

    def test_missing_user_id_is_rejected(self):
        with self.assertRaises(CLI.SetupError):
            CLI.active_linkedin_account(self.StubAPI([]), '')

    def test_multiple_active_accounts_ask_for_a_pin(self):
        api = self.StubAPI([self.linkedin('acc-1'), self.linkedin('acc-2')])
        with patch.dict(os.environ, {'COMPOSIO_CONNECTED_ACCOUNT_ID': ''}):
            with self.assertRaises(CLI.SetupError) as caught:
                CLI.active_linkedin_account(api, 'gungun')
        self.assertIn('Multiple ACTIVE LinkedIn accounts', str(caught.exception))
        self.assertIn('acc-1, acc-2', str(caught.exception))

    def test_pinned_account_is_selected(self):
        api = self.StubAPI([self.linkedin('acc-1'), self.linkedin('acc-2')])
        with patch.dict(os.environ, {'COMPOSIO_CONNECTED_ACCOUNT_ID': 'acc-2'}):
            self.assertEqual(CLI.active_linkedin_account(api, 'gungun')['id'], 'acc-2')

    def test_no_active_connection_explains_the_fix(self):
        api = self.StubAPI([self.linkedin('acc-9', status='EXPIRED')])
        with patch.dict(os.environ, {'COMPOSIO_CONNECTED_ACCOUNT_ID': ''}):
            with self.assertRaises(CLI.SetupError) as caught:
                CLI.active_linkedin_account(api, 'gungun')
        self.assertIn('No ACTIVE LinkedIn connection', str(caught.exception))

    def test_disabled_accounts_are_ignored(self):
        api = self.StubAPI([self.linkedin('acc-1', is_disabled=True), self.linkedin('acc-2')])
        self.assertEqual(CLI.active_linkedin_account(api, 'gungun')['id'], 'acc-2')

    def test_author_from_profile_prefers_an_explicit_urn(self):
        response = {'data': {'author': 'urn:li:person:aBc-123'}}
        self.assertEqual(CLI.author_from_profile(response), 'urn:li:person:aBc-123')

    def test_author_from_profile_wraps_a_bare_member_id(self):
        self.assertEqual(CLI.author_from_profile({'data': {'profile': {'id': '777abc'}}}),
                         'urn:li:person:777abc')

    def test_author_from_profile_never_guesses(self):
        self.assertIsNone(CLI.author_from_profile({'data': {'fullName': 'Gungun'}}))

    def test_get_author_uses_the_configured_urn(self):
        with patch.dict(os.environ, {'LINKEDIN_AUTHOR_URN': 'urn:li:person:abc123'}):
            self.assertEqual(CLI.get_author(None, 'user', 'account'), 'urn:li:person:abc123')

    def test_get_author_rejects_a_malformed_urn(self):
        with patch.dict(os.environ, {'LINKEDIN_AUTHOR_URN': 'person:abc'}):
            with self.assertRaises(CLI.SetupError):
                CLI.get_author(None, 'user', 'account')


class CommandLineTests(unittest.TestCase):
    def draft(self, directory, body='Approved file content\n\n#TestTag', name='draft.md'):
        path = Path(directory) / name
        path.write_text(body, encoding='utf-8')
        return path

    def test_dry_run_from_file_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.draft(directory)
            code, stdout, stderr, calls, _ = run_cli(['--dry-run', '--file', str(path)])
            self.assertEqual(code, 0, stderr)
            self.assertIn('Approved file content', stdout)
            self.assertIn('DRY RUN', stdout)
            self.assertEqual(calls, [])

    def test_dry_run_with_inline_text_does_not_publish(self):
        code, stdout, stderr, calls, _ = run_cli(['--dry-run', 'Inline text'])
        self.assertEqual(code, 0, stderr)
        self.assertIn('Inline text', stdout)
        self.assertEqual(calls, [])

    def test_publish_sends_exactly_the_expected_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.draft(directory, body='Publish me')
            code, stdout, stderr, calls, _ = run_cli(['--publish', '--file', str(path)])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(calls, [{'tool': CLI.POST_SLUG, 'account_id': 'account-1',
                                      'user_id': 'file-user',
                                      'arguments': {'author': 'urn:li:person:test',
                                                    'commentary': 'Publish me',
                                                    'visibility': 'PUBLIC'}}])
            self.assertIn('Publishing...', stdout)

    def test_text_and_file_together_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.draft(directory)
            code, _, stderr, calls, _ = run_cli(['--dry-run', 'Text', '--file', str(path)])
            self.assertEqual(code, 1)
            self.assertIn('either', stderr.lower())
            self.assertEqual(calls, [])

    def test_missing_text_and_file_are_rejected(self):
        code, _, stderr, calls, _ = run_cli(['--dry-run'])
        self.assertEqual(code, 1)
        self.assertIn('Supply either inline text or --file', stderr)
        self.assertEqual(calls, [])

    def test_file_with_inspect_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.draft(directory)
            code, _, stderr, calls, _ = run_cli(['--inspect', '--file', str(path)])
            self.assertEqual(code, 1)
            self.assertIn('--file can only be used', stderr)
            self.assertEqual(calls, [])

    def test_inspect_prints_the_tool_schema(self):
        code, stdout, stderr, calls, _ = run_cli(['--inspect'])
        self.assertEqual(code, 0, stderr)
        schema = json.loads(stdout)
        self.assertEqual(schema['tool_slug'], CLI.POST_SLUG)
        self.assertEqual(schema['version'], '20261026_00')
        self.assertIn('commentary', schema['input_parameters'])
        self.assertEqual(calls, [])

    def test_discovered_env_file_is_reported_and_used(self):
        code, stdout, stderr, _, key = run_cli(['--dry-run', 'Hello'])
        self.assertEqual(code, 0, stderr)
        self.assertIn('Env file:', stdout)
        self.assertIn('(from parent directory)', stdout)
        self.assertEqual(key, 'file-api-key')

    def test_skill_root_env_file_wins_over_neighbourhood_files(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / 'skill'
            skill.mkdir()
            (skill / '.env').write_text('COMPOSIO_API_KEY=skill-key\nCOMPOSIO_USER_ID=u\n',
                                        encoding='utf-8')
            code, stdout, stderr, _, key = run_cli(['--dry-run', 'Hello'], skill_root=skill)
            self.assertEqual(code, 0, stderr)
            self.assertIn('(from skill root)', stdout)
            self.assertEqual(key, 'skill-key')

    def test_missing_env_file_falls_back_to_the_process_environment(self):
        code, stdout, stderr, _, key = run_cli(
            ['--dry-run', 'Hello'], env={'COMPOSIO_API_KEY': 'env-key',
                                        'COMPOSIO_USER_ID': 'env-user'},
            make_env_file=False)
        self.assertEqual(code, 0, stderr)
        self.assertIn('Env file: none found', stdout)
        self.assertEqual(key, 'env-key')

    def test_explicit_env_file_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / 'custom.env'
            env.write_text('COMPOSIO_API_KEY=explicit-key\nCOMPOSIO_USER_ID=u\n', encoding='utf-8')
            code, stdout, stderr, _, key = run_cli(['--dry-run', 'Hello', '--env-file', str(env)],
                                                   make_env_file=False)
            self.assertEqual(code, 0, stderr)
            self.assertIn('(from flag)', stdout)
            self.assertEqual(key, 'explicit-key')

    def test_missing_explicit_env_file_is_an_error(self):
        code, _, stderr, calls, _ = run_cli(['--dry-run', 'Hello', '--env-file', '/no/such/.env'])
        self.assertEqual(code, 1)
        self.assertIn('Env file not found', stderr)
        self.assertEqual(calls, [])

    def test_absent_api_key_is_reported_before_any_request(self):
        code, _, stderr, calls, _ = run_cli(['--dry-run', 'Hello'], make_env_file=False)
        self.assertEqual(code, 1)
        self.assertIn('COMPOSIO_API_KEY is missing', stderr)
        self.assertEqual(calls, [])

    def test_max_chars_rejects_a_long_post(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.draft(directory, body='x' * 50)
            code, _, stderr, calls, _ = run_cli(['--dry-run', '--file', str(path),
                                                 '--max-chars', '30'])
            self.assertEqual(code, 1)
            self.assertIn('20 over the 30-character limit', stderr)
            self.assertEqual(calls, [])

    def test_max_chars_rejects_an_invalid_limit(self):
        code, _, stderr, _, _ = run_cli(['--dry-run', 'Hello', '--max-chars', '0'])
        self.assertEqual(code, 1)
        self.assertIn('--max-chars', stderr)

    def test_extra_json_behaviour(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.draft(directory, body='Extra fields')
            code, _, stderr, calls, _ = run_cli(
                ['--publish', '--file', str(path), '--extra', '{"visibility": "CONNECTIONS"}'])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(calls[0]['arguments']['visibility'], 'CONNECTIONS')

            code, _, stderr, calls, _ = run_cli(['--dry-run', 'Text', '--extra', '{"nope": 1}'])
            self.assertEqual(code, 1)
            self.assertIn('Unknown extra argument(s): nope', stderr)
            self.assertEqual(calls, [])

            code, _, stderr, _, _ = run_cli(['--dry-run', 'Text', '--extra', 'not-json'])
            self.assertEqual(code, 1)
            self.assertIn('invalid JSON', stderr)

            code, _, stderr, _, _ = run_cli(['--dry-run', 'Text', '--extra', '[1, 2]'])
            self.assertEqual(code, 1)
            self.assertIn('must be a JSON object', stderr)

    def test_docx_is_publishable_from_the_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_docx(directory)
            code, _, stderr, calls, _ = run_cli(['--publish', '--file', str(path)])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(calls[0]['arguments']['commentary'], 'Hello world\nCell\nLast\tline')


class JsonOutputTests(unittest.TestCase):
    def test_dry_run_json_has_documented_keys_and_no_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.md'
            path.write_text('Body here\n\n#Alpha #Beta #Alpha\n', encoding='utf-8')
            code, stdout, stderr, calls, _ = run_cli(['--dry-run', '--file', str(path), '--json'])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(calls, [])
            payload = json.loads(stdout)  # the whole stdout must be one JSON document
        self.assertEqual(payload['mode'], 'dry-run')
        for key in ('mode', 'env_file', 'account_id', 'user_id', 'author', 'toolkit_version',
                    'visibility', 'text', 'char_count', 'hashtags', 'arguments', 'published',
                    'log_id', 'data'):
            self.assertIn(key, payload)
        self.assertFalse(payload['published'])
        self.assertIsNone(payload['data'])
        self.assertEqual(payload['text'], 'Body here\n\n#Alpha #Beta #Alpha\n')
        self.assertEqual(payload['char_count'], len(payload['text']))
        self.assertEqual(payload['hashtags'], ['#Alpha', '#Beta'])
        self.assertEqual(payload['account_id'], 'account-1')
        self.assertEqual(payload['user_id'], 'file-user')
        self.assertEqual(payload['author'], 'urn:li:person:test')
        self.assertEqual(payload['visibility'], 'PUBLIC')
        self.assertEqual(payload['toolkit_version'], '20261026_00')
        self.assertEqual(payload['arguments']['commentary'], payload['text'])
        self.assertTrue(payload['env_file'].endswith('.env'))

    def test_publish_json_reports_log_id_and_data(self):
        code, stdout, stderr, calls, _ = run_cli(['--publish', 'Go live', '--json'])
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload['mode'], 'publish')
        self.assertTrue(payload['published'])
        self.assertEqual(payload['log_id'], 'log-1')
        self.assertEqual(payload['data'], {'id': 'post-1'})
        self.assertEqual(payload['char_count'], len('Go live'))
        self.assertEqual(len(calls), 1)

    def test_inspect_json_is_only_the_schema_object(self):
        code, stdout, stderr, _, _ = run_cli(['--inspect', '--json'])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(sorted(json.loads(stdout)),
                         ['input_parameters', 'tool_slug', 'version'])

    def test_json_env_file_reports_the_resolved_path(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / 'clean.env'
            env.write_text('COMPOSIO_API_KEY=k\nCOMPOSIO_USER_ID=u\n', encoding='utf-8')
            code, stdout, stderr, _, _ = run_cli(['--dry-run', 'Hello', '--json',
                                                 '--env-file', str(env)])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)['env_file'], str(env))

    def test_errors_stay_on_stderr_in_json_mode(self):
        code, stdout, stderr, _, _ = run_cli(['--dry-run', 'x' * 40, '--json', '--max-chars', '5'])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertTrue(stderr.startswith('ERROR:'))


class UrllibClientTests(unittest.TestCase):
    """The stdlib client must raise the same friendly errors as the old requests build."""

    def make_client(self):
        return CLI.ComposioAPI('test-key')

    def test_get_sends_headers_and_query_parameters(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen['url'] = request.full_url
            seen['headers'] = dict(request.headers)
            seen['timeout'] = timeout
            return FakeResponse({'items': [{'slug': 'x'}]})

        with patch.object(CLI, 'urlopen', fake_urlopen):
            items = self.make_client().linkedin_tools()
        self.assertEqual(items, [{'slug': 'x'}])
        self.assertIn('/api/v3.1/tools?', seen['url'])
        self.assertIn('toolkit_slug=linkedin', seen['url'])
        self.assertEqual(seen['headers'].get('X-api-key'), 'test-key')
        self.assertEqual(seen['timeout'], 30)

    def test_post_sends_a_json_body_and_returns_the_response(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen['method'] = request.get_method()
            seen['body'] = json.loads(request.data.decode('utf-8'))
            seen['type'] = request.headers.get('Content-type')
            return FakeResponse({'successful': True, 'data': {'id': 'p'}, 'log_id': 'l'})

        tool = {'slug': CLI.POST_SLUG, 'version': '20261026_00'}
        with patch.object(CLI, 'urlopen', fake_urlopen):
            result = self.make_client().execute(tool, 'user', 'account', {'commentary': 'hi'})
        self.assertTrue(result['successful'])
        self.assertEqual(seen['method'], 'POST')
        self.assertEqual(seen['type'], 'application/json')
        self.assertEqual(seen['body']['arguments'], {'commentary': 'hi'})
        self.assertEqual(seen['body']['version'], '20261026_00')

    def test_http_error_becomes_a_friendly_setup_error(self):
        def raise_401(request, timeout=None):
            raise CLI.HTTPError(request.full_url, 401, 'Unauthorized', Message(),
                                io.BytesIO(b'{"detail":"bad key"}'))

        with patch.object(CLI, 'urlopen', raise_401):
            with self.assertRaises(CLI.SetupError) as caught:
                self.make_client().linkedin_tools()
        message = str(caught.exception)
        self.assertIn('Composio HTTP 401', message)
        self.assertIn('Check COMPOSIO_API_KEY and project', message)

    def test_network_error_becomes_a_friendly_setup_error(self):
        def refuse(request, timeout=None):
            raise CLI.URLError('no route to host')

        with patch.object(CLI, 'urlopen', refuse):
            with self.assertRaises(CLI.SetupError) as caught:
                self.make_client().linkedin_tools()
        self.assertIn('Network error contacting Composio', str(caught.exception))

    def test_non_json_error_body_is_wrapped_as_a_message(self):
        with patch.object(CLI, 'urlopen', lambda request, timeout=None:
                          FakeResponse('<html>gateway</html>', status=502)):
            with self.assertRaises(CLI.SetupError) as caught:
                self.make_client().linkedin_tools()
        self.assertIn('Composio HTTP 502', str(caught.exception))
        self.assertIn('gateway', str(caught.exception))

    def test_unsuccessful_execution_is_reported(self):
        with patch.object(CLI, 'urlopen', lambda request, timeout=None:
                          FakeResponse({'successful': False, 'error': 'denied'})):
            with self.assertRaises(CLI.SetupError) as caught:
                self.make_client().execute({'slug': 'T'}, 'u', 'a', {})
        self.assertIn('execution failed', str(caught.exception))

    def test_missing_api_key_is_reported_by_the_constructor(self):
        with self.assertRaises(CLI.SetupError):
            CLI.ComposioAPI('')


class StageDraftTests(unittest.TestCase):
    def test_slugify_normalises_the_first_line(self):
        self.assertEqual(STAGE.slugify('  Hiring: what I learned 👋\n\nmore'),
                         'hiring-what-i-learned')
        self.assertEqual(STAGE.slugify('!!!!'), 'post')
        self.assertEqual(STAGE.slugify(''), 'post')
        self.assertLessEqual(len(STAGE.slugify('a' * 90)), 40)

    def test_write_creates_a_dated_file_under_posts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = STAGE.write_draft(directory, 'My first post\n\nBody')
            self.assertEqual(path.parent, (Path(directory) / 'posts').resolve())
            self.assertRegex(path.name, r'^\d{4}-\d{2}-\d{2}-my-first-post\.md$')
            self.assertEqual(path.read_text(encoding='utf-8'), 'My first post\n\nBody\n')

    def test_extension_and_slug_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = STAGE.write_draft(directory, 'Body', slug='Release Notes', ext='txt')
            self.assertRegex(path.name, r'^\d{4}-\d{2}-\d{2}-release-notes\.txt$')
            with self.assertRaises(ValueError):
                STAGE.write_draft(directory, 'Body', ext='pdf')

    def test_never_overwrites_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            first = STAGE.write_draft(directory, 'Same headline\nv1')
            second = STAGE.write_draft(directory, 'Same headline\nv2')
            third = STAGE.write_draft(directory, 'Same headline\nv3')
            self.assertRegex(first.name, r'^\d{4}-\d{2}-\d{2}-same-headline\.md$')
            self.assertEqual(second.name, first.stem + '-2.md')
            self.assertEqual(third.name, first.stem + '-3.md')
            self.assertEqual(second.read_text(encoding='utf-8'), 'Same headline\nv2\n')
            self.assertEqual(first.read_text(encoding='utf-8'), 'Same headline\nv1\n')
            forced = STAGE.write_draft(directory, 'Same headline\nv4', force=True)
            self.assertEqual(forced, first)
            self.assertEqual(len(list((Path(directory) / 'posts').iterdir())), 3)

    def test_empty_body_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                STAGE.write_draft(directory, '   \n')

    def test_main_prints_only_the_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            output, error = io.StringIO(), io.StringIO()
            argv = ['stage_draft.py', '--workspace', directory, '--text', 'Headline here']
            with patch.object(STAGE.sys, 'argv', argv), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = STAGE.main()
            printed = output.getvalue()
            self.assertEqual(code, 0, error.getvalue())
            self.assertEqual(printed.strip(), str(Path(printed.strip()).resolve()))
            self.assertEqual(len(printed.strip().splitlines()), 1)
            self.assertTrue(Path(printed.strip()).is_file())

    def test_main_reads_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            argv = ['stage_draft.py', '--workspace', directory, '--stdin']
            with patch.object(STAGE.sys, 'argv', argv), \
                 patch.object(STAGE.sys, 'stdin', io.StringIO('From stdin\n')):
                with contextlib.redirect_stdout(output):
                    code = STAGE.main()
            self.assertEqual(code, 0)
            self.assertEqual(Path(output.getvalue().strip()).read_text(encoding='utf-8'),
                             'From stdin\n')

    def test_main_without_a_body_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            output, error = io.StringIO(), io.StringIO()
            argv = ['stage_draft.py', '--workspace', directory]
            with patch.object(STAGE.sys, 'argv', argv), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = STAGE.main()
            self.assertEqual(code, 1)
            self.assertEqual(output.getvalue(), '')
            self.assertIn('ERROR:', error.getvalue())

    def test_list_reports_staged_drafts(self):
        with tempfile.TemporaryDirectory() as directory:
            STAGE.write_draft(directory, 'Alpha draft')
            STAGE.write_draft(directory, 'Beta draft')
            rows = STAGE.list_drafts(directory)
            self.assertEqual(len(rows), 2)
            name, size, stamp = rows[0]
            self.assertTrue(name.endswith('.md'))
            self.assertGreater(size, 0)
            self.assertRegex(stamp, r'^\d{4}-\d{2}-\d{2}$')

    def test_list_of_a_workspace_without_drafts_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(STAGE.list_drafts(directory), [])


class RepoRootWrapperTests(unittest.TestCase):
    """The repository wrapper must keep the documented public names available."""

    @classmethod
    def setUpClass(cls):
        wrapper = REPO_ROOT / 'post_linkedin.py'
        if not wrapper.is_file():
            raise unittest.SkipTest('bundle is running standalone: no repository wrapper present')
        spec = importlib.util.spec_from_file_location('repo_post_linkedin', str(wrapper))
        cls.wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.wrapper)

    def test_documented_names_are_exposed(self):
        for name in ('SetupError', 'POST_SLUG', 'PROFILE_SLUG', 'ComposioAPI', 'read_post_file',
                     'active_linkedin_account', 'author_from_profile', 'get_author',
                     'tool_schema', 'make_arguments', 'main'):
            self.assertTrue(hasattr(self.wrapper, name), name)
        self.assertEqual(self.wrapper.POST_SLUG, CLI.POST_SLUG)

    def test_skill_root_points_at_the_bundle(self):
        self.assertEqual(Path(self.wrapper.SKILL_ROOT), BUNDLE_ROOT)


class DoctorTests(unittest.TestCase):
    """doctor.py is read-only: it must report, mask, and exit honestly."""

    class NetworkBoom:
        def __init__(self, key):
            pass

        def linkedin_tools(self):
            raise CLI.SetupError('Network error contacting Composio: [Errno 111] refused')

    class RejectedBoom:
        def __init__(self, key):
            pass

        def linkedin_tools(self):
            raise CLI.SetupError('Composio HTTP 401: {"detail":"invalid key"} '
                                 '(Check COMPOSIO_API_KEY and project.)')

    def run_doctor(self, extra_args=(), env_text="COMPOSIO_API_KEY=sk-secret-abcdefghij\n"
                                                 "COMPOSIO_USER_ID=gungun\n", api=None):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / 'clean.env'
            env.write_text(env_text, encoding='utf-8')
            output, error = io.StringIO(), io.StringIO()
            argv = ['doctor.py', '--env-file', str(env), '--workspace', directory] + list(extra_args)
            patches = [patch.object(DOCTOR, 'load_cli', lambda: CLI),
                       patch.object(DOCTOR.sys, 'argv', argv),
                       patch.dict(os.environ, {}, clear=True),
                       contextlib.redirect_stdout(output),
                       contextlib.redirect_stderr(error)]
            if api is not None:
                patches.append(patch.object(CLI, 'ComposioAPI', api))
            with contextlib.ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                code = DOCTOR.main()
            return code, output.getvalue(), error.getvalue()

    def test_ready_and_no_secret_is_printed(self):
        code, stdout, _ = self.run_doctor()
        self.assertEqual(code, 0)
        self.assertIn('RESULT: READY', stdout)
        self.assertNotIn('sk-secret-abcdefghij', stdout)
        self.assertIn('(from flag)', stdout)
        self.assertIn('masked', stdout)
        self.assertIn('no third-party packages', stdout)

    def test_missing_required_keys_fail(self):
        code, stdout, _ = self.run_doctor(env_text='COMPOSIO_USER_ID=gungun\n')
        self.assertEqual(code, 1)
        self.assertIn('COMPOSIO_API_KEY : MISSING', stdout)
        self.assertIn('RESULT: FAILED', stdout)

    def test_posts_directory_is_reported(self):
        code, stdout, _ = self.run_doctor()
        self.assertIn('posts directory', stdout)
        self.assertRegex(stdout, r'posts directory\s*: .*[/\\]posts')

    def test_check_api_network_error_is_skipped_not_failed(self):
        code, stdout, _ = self.run_doctor(['--check-api'], api=self.NetworkBoom)
        self.assertEqual(code, 0)
        self.assertIn('[SKIP] live API check', stdout)
        self.assertIn('RESULT: READY', stdout)

    def test_check_api_reports_an_accepted_key(self):
        code, stdout, _ = self.run_doctor(['--check-api'], api=FakeAPI)
        self.assertEqual(code, 0)
        self.assertIn('live API check', stdout)
        self.assertIn('accepted', stdout)

    def test_check_api_authentication_failure_is_a_failure(self):
        code, stdout, _ = self.run_doctor(['--check-api'], api=self.RejectedBoom)
        self.assertEqual(code, 1)
        self.assertIn('[FAIL] live API check', stdout)

    def test_check_api_without_a_key_skips_the_live_test(self):
        code, stdout, _ = self.run_doctor(['--check-api'], env_text='COMPOSIO_USER_ID=gungun\n')
        self.assertEqual(code, 1)
        self.assertIn('[SKIP] live API check', stdout)
        self.assertIn('COMPOSIO_API_KEY : MISSING', stdout)

    def test_bad_env_file_path_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            output, error = io.StringIO(), io.StringIO()
            argv = ['doctor.py', '--env-file', str(Path(directory) / 'absent.env')]
            with patch.object(DOCTOR, 'load_cli', lambda: CLI), \
                 patch.object(DOCTOR.sys, 'argv', argv), \
                 patch.dict(os.environ, {}, clear=True), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = DOCTOR.main()
            self.assertEqual(code, 1)
            self.assertIn('Env file not found', output.getvalue())


class BundleHygieneTests(unittest.TestCase):
    def test_no_third_party_imports_anywhere_in_the_bundle(self):
        forbidden = re.compile(r'^\s*(import|from)\s+(requests|dotenv|composio)\b', re.MULTILINE)
        scripts = sorted(SCRIPTS.glob('*.py'))
        self.assertTrue(scripts)
        for path in scripts + [Path(__file__)]:
            with self.subTest(path=str(path.relative_to(BUNDLE_ROOT))):
                self.assertIsNone(forbidden.search(path.read_text(encoding='utf-8')))

    def test_importing_the_cli_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory) / 'scripts'
            scripts.mkdir()
            copy = scripts / 'post_linkedin.py'
            shutil.copyfile(str(SCRIPTS / 'post_linkedin.py'), str(copy))
            spec = importlib.util.spec_from_file_location('isolated_cli', str(copy))
            module = importlib.util.module_from_spec(spec)
            before = sorted(os.environ)
            spec.loader.exec_module(module)
            self.assertEqual(sorted(os.environ), before)
            self.assertEqual(Path(module.SKILL_ROOT), Path(directory).resolve())
            self.assertEqual(sorted(os.environ), before)


if __name__ == '__main__':
    unittest.main()
