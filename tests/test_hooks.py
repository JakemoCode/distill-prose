import json
import os
import subprocess
import sys
import tempfile
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

    def test_a_stop_during_an_agent_distillation_is_reported_to_the_user(self):
        script = ROOT / 'skills' / 'distill' / 'scripts' / 'distill.py'
        cli = lambda *a: subprocess.run([sys.executable, str(script), str(self.doc), *a],
                                        capture_output=True, text=True, env=self.env)
        cli()  # trusts the stamp and starts its sidecar entry
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        cli('--agent')
        cli('--stop')
        self.assertEqual(cli('--reviewed').returncode, 0)
        answer = self.hook('stop', stop_hook_active=False)
        self.assertIn('stopped early', answer['systemMessage'])

    def test_an_unstamped_doc_is_not_watched(self):
        other = self.dir / 'notes.md'
        other.write_text(paragraphs(3))
        self.agent_appends('\n' + paragraphs(9, tag='a'), doc=other)
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def test_dictated_text_does_not_block(self):
        self.agent_appends('\n' + paragraphs(6, tag='a'))
        script = ROOT / 'skills' / 'distill' / 'scripts' / 'distill.py'
        subprocess.run([sys.executable, str(script), str(self.doc), '--dictated'],
                       capture_output=True, env=self.env)
        self.assertIsNone(self.hook('stop', stop_hook_active=False))

    def test_the_hook_config_points_at_this_script(self):
        config = json.loads((ROOT / 'hooks' / 'hooks.json').read_text())['hooks']
        self.assertEqual(set(config), {'PreToolUse', 'PostToolUse', 'Stop'})
        for entries in config.values():
            self.assertIn('${CLAUDE_PLUGIN_ROOT}/hooks/edit.py', entries[0]['hooks'][0]['command'])


if __name__ == '__main__':
    unittest.main()
