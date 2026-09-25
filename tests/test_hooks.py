import json
import re
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'hooks' / 'edit.py'
sys.path.insert(0, str(ROOT / 'skills' / 'distill' / 'scripts'))
import prose  # noqa: E402
from test_distill import paragraphs  # noqa: E402

STAMP = prose.format_stamp('abc123', 'aggressive', 200, 90)


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()
        self.store = tempfile.TemporaryDirectory()
        # The hooks keep what a session owes under the system temp directory.
        self.env = {**os.environ, 'TMPDIR': self.store.name}
        self.doc = self.dir / 'AGENTS.md'
        self.doc.write_text(f'{STAMP}\n{paragraphs(9)}')

    def tearDown(self):
        self.tmp.cleanup()
        self.store.cleanup()

    def hook(self, event, **fields):
        payload = {'session_id': 's1', **fields}
        done = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def agent_appends(self, text, doc=None):
        doc = doc or self.doc
        self.hook('pre', tool_name='Edit', tool_input={'file_path': str(doc)})
        doc.write_text(doc.read_text() + text)
        self.hook('post', tool_name='Edit', tool_input={'file_path': str(doc)})

    def test_an_agent_addition_over_the_floor_blocks_the_stop(self):
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        answer = self.hook('stop', stop_hook_active=False)
        self.assertEqual(answer['decision'], 'block')
        self.assertIn('60 prose words', answer['reason'])
        self.assertIn('--agent', answer['reason'])

    def test_the_second_stop_is_let_through_with_a_warning(self):
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        answer = self.hook('stop', stop_hook_active=True)
        self.assertNotIn('decision', answer)
        self.assertIn('still undistilled', answer['systemMessage'])

    def test_an_addition_under_the_floor_does_not_block(self):
        self.agent_appends('\n' + paragraphs(3, tag='a'))
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def test_small_additions_add_up(self):
        for n in range(3):
            self.agent_appends('\n' + paragraphs(2, tag=f'a{n}'))
        self.assertEqual(self.hook('stop', stop_hook_active=False)['decision'], 'block')

    def test_editing_owed_text_again_does_not_launder_it(self):
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        self.hook('pre', tool_name='Edit', tool_input={'file_path': str(self.doc)})
        self.doc.write_text(self.doc.read_text().replace('bravo', 'bravvo'))  # a typo fix in every block
        self.hook('post', tool_name='Edit', tool_input={'file_path': str(self.doc)})
        self.assertEqual(self.hook('stop', stop_hook_active=False)['decision'], 'block')

    def test_the_skills_own_passes_are_not_billed_as_agent_text(self):
        script = ROOT / 'skills' / 'distill' / 'scripts' / 'distill.py'
        cli = lambda *a: subprocess.run([sys.executable, str(script), str(self.doc), *a],
                                        capture_output=True, text=True, env=self.env)
        cli()  # the stamp has no sidecar entry yet, so this trusts it and starts one
        self.doc.write_text(self.doc.read_text() + '\n' + paragraphs(6, tag='h'))
        cli()  # a distillation of the human's addition is now running on the doc
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        cli('--reset')
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def cli(self, *args):
        script = ROOT / 'skills' / 'distill' / 'scripts' / 'distill.py'
        return subprocess.run([sys.executable, str(script), str(self.doc), *args],
                              capture_output=True, text=True, env=self.env)

    def test_the_agent_cannot_stop_a_distillation_the_user_did_not_accept(self):
        self.cli()  # trusts the stamp and starts its sidecar entry
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        self.cli('--agent')
        refused = self.cli('--stop')
        self.assertNotIn('blind review', refused.stdout)
        phrase = re.search(r'accept [0-9a-f]{6}', refused.stdout).group(0)

        self.hook('prompt', prompt=f'ok, {phrase}')
        self.assertIn('blind review', self.cli('--stop').stdout)

    def test_a_hook_that_hits_an_error_stays_silent(self):
        # A hook error shows on every edit. For a stranger that reads as a broken plugin.
        broken = self.dir / 'latin1.md'
        broken.write_bytes(STAMP.encode() + b'\ncaf\xe9 au lait\n')
        for event in ('pre', 'post'):
            done = subprocess.run([sys.executable, str(HOOK), event], capture_output=True, text=True, env=self.env,
                                  input=json.dumps({'session_id': 's1', 'tool_input': {'file_path': str(broken)}}))
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), event)

    def test_an_unstamped_doc_is_not_watched(self):
        other = self.dir / 'notes.md'
        other.write_text(paragraphs(3))
        self.agent_appends('\n' + paragraphs(9, tag='a'), doc=other)
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def test_text_the_user_typed_is_not_billed(self):
        dictated = paragraphs(6, tag='u')
        self.hook('prompt', prompt=f'Add exactly this to AGENTS.md:\n\n{dictated}')
        self.agent_appends('\n- ' + dictated.replace('\n\n', '\n- '))  # as a list, in backticks-free markdown
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def test_a_light_copyedit_of_dictated_text_still_counts_as_the_users(self):
        dictated = paragraphs(6, tag='u')
        self.hook('prompt', prompt=f'Add this: {dictated}')
        self.agent_appends('\n' + dictated.replace('golf', 'gulf', 1))
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def test_text_the_agent_wrote_from_a_request_is_billed(self):
        self.hook('prompt', prompt='Add a troubleshooting section about the port being in use.')
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        self.assertEqual(self.hook('stop', stop_hook_active=False)['decision'], 'block')

    def test_the_stop_hook_never_offers_the_agent_a_way_out(self):
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        self.assertNotIn('dictated', self.hook('stop', stop_hook_active=False)['reason'])

    def test_the_hook_config_points_at_this_script(self):
        config = json.loads((ROOT / 'hooks' / 'hooks.json').read_text())['hooks']
        self.assertEqual(set(config), {'PreToolUse', 'PostToolUse', 'Stop', 'UserPromptSubmit'})
        for entries in config.values():
            self.assertIn('${CLAUDE_PLUGIN_ROOT}/hooks/edit.py', entries[0]['hooks'][0]['command'])


class PromptLog(unittest.TestCase):
    """What the hooks keep of what the user typed: little, and not for long."""

    def setUp(self):
        self.store = tempfile.TemporaryDirectory()
        self.env = {**os.environ, 'TMPDIR': self.store.name}
        self.sessions = Path(self.store.name) / f'distill-prose-{os.getuid()}'

    def tearDown(self):
        self.store.cleanup()

    def prompt(self, text, session='s1'):
        done = subprocess.run([sys.executable, str(HOOK), 'prompt'],
                              input=json.dumps({'session_id': session, 'prompt': text}),
                              capture_output=True, text=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_prompt_log_is_readable_only_by_its_user(self):
        self.prompt('something private')
        self.assertEqual(self.sessions.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.sessions / 's1.json').stat().st_mode & 0o777, 0o600)

    def test_a_store_that_already_exists_open_to_others_is_closed(self):
        self.sessions.mkdir()
        self.sessions.chmod(0o755)
        self.prompt('something private')
        self.assertEqual(self.sessions.stat().st_mode & 0o777, 0o700)

    def test_a_store_that_is_a_symlink_is_never_written_through(self):
        # On a shared /tmp, another user could plant a link where the store goes.
        elsewhere = Path(self.store.name) / 'elsewhere'
        elsewhere.mkdir()
        self.sessions.symlink_to(elsewhere)
        self.prompt('something private')
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_the_world_readable_log_from_0_3_1_is_removed(self):
        legacy = Path(self.store.name) / 'distill-prose'
        legacy.mkdir()
        (legacy / 'old-session.json').write_text('{"prompts": ["private"]}')
        self.prompt('hello')
        self.assertFalse(legacy.exists())

    def test_only_the_last_ten_prompts_are_kept(self):
        for n in range(12):
            self.prompt(f'prompt number {n}')
        kept = json.loads((self.sessions / 's1.json').read_text())['prompts']
        self.assertEqual(kept, [f'prompt number {n}' for n in range(2, 12)])

    def test_a_session_untouched_for_a_day_is_deleted_when_any_hook_runs(self):
        self.prompt('old session', session='old')
        self.prompt('recent session', session='recent')
        day_and_an_hour_ago = time.time() - 25 * 3600
        os.utime(self.sessions / 'old.json', (day_and_an_hour_ago, day_and_an_hour_ago))

        self.prompt('a new prompt', session='other')
        self.assertFalse((self.sessions / 'old.json').exists())
        self.assertTrue((self.sessions / 'recent.json').exists())


if __name__ == '__main__':
    unittest.main()
