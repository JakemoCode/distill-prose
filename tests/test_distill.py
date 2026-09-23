import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'skills' / 'distill' / 'scripts'))
import distill  # noqa: E402
import pending  # noqa: E402
import prose  # noqa: E402

WORDS = 'alpha bravo charlie delta echo foxtrot golf hotel india juliet'.split()


def paragraphs(n, tag='p'):
    """n distinct ten-word paragraphs."""
    return '\n\n'.join(' '.join(f'{w}{tag}{i}' if j == 0 else w for j, w in enumerate(WORDS)) for i in range(n)) + '\n'


def prose_words(n):
    """A doc of exactly n prose words, in ten-word paragraphs."""
    words = [f'{WORDS[i % 10]}w{i}' for i in range(n)]
    return '\n\n'.join(' '.join(words[i:i + 10]) for i in range(0, n, 10)) + '\n'


def text_of(result):
    return '\n'.join(result[1])


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name).resolve()
        self.doc = self.dir / 'guide.md'
        self.store = tempfile.TemporaryDirectory()
        self.saved_store = pending.STORE
        pending.STORE = Path(self.store.name)

    def tearDown(self):
        pending.STORE = self.saved_store
        self.tmp.cleanup()
        self.store.cleanup()

    def write(self, text):
        self.doc.write_text(text)

    def run_step(self, flag=None, preset=None):
        return distill.step(self.doc, flag, preset)

    def distill_fresh(self, flag_last='reviewed'):
        """Take a 200-word doc through grammar, shape and fluff passes to DONE."""
        self.write(paragraphs(20))
        self.run_step()
        self.write(paragraphs(19))
        self.run_step()
        self.write(paragraphs(14))
        self.run_step()
        self.write(paragraphs(9))
        self.run_step()
        return self.run_step(flag_last)

    def test_the_first_run_records_the_peak_and_asks_for_the_grammar_pass(self):
        self.write(paragraphs(20))
        done, lines = self.run_step()
        self.assertFalse(done)
        self.assertIn('200 prose words to distill', text_of((done, lines)))
        self.assertIn('Pass 1 (grammar)', text_of((done, lines)))

    def test_a_fresh_doc_goes_through_review_to_a_stamp_and_a_sidecar_entry(self):
        self.write(paragraphs(20))
        self.run_step()
        self.write(paragraphs(19))
        self.assertIn('Pass 2 (shape)', text_of(self.run_step()))
        self.write(paragraphs(14))
        self.assertIn('Pass 3 (fluff)', text_of(self.run_step()))
        self.write(paragraphs(9))
        self.assertIn('Next: a blind review', text_of(self.run_step()))

        done, lines = self.run_step('reviewed')
        self.assertTrue(done)
        stamp = prose.read_stamp(self.doc.read_text())
        self.assertEqual((stamp['preset'], stamp['curve']), ('aggressive', [200, 90]))
        entry = json.loads((self.dir / '.distill.json').read_text())[stamp['id']]
        self.assertEqual(entry['path'], 'guide.md')
        self.assertFalse((self.dir / '.distill').exists())

    def test_finishing_one_doc_keeps_the_scratch_of_another_doc_in_progress(self):
        other = self.dir / 'other.md'
        other.write_text(paragraphs(20, tag='o'))
        distill.step(other)
        self.distill_fresh()
        self.assertTrue((self.dir / '.distill' / 'other.md' / 'state.json').exists())

    def test_a_grammar_pass_that_cuts_is_refused_and_undo_restores_the_doc(self):
        self.write(paragraphs(20))
        self.run_step()
        self.write(paragraphs(10))
        done, lines = self.run_step()
        self.assertIn('Pass 1 removed 50%', text_of((done, lines)))
        self.run_step('undo')
        self.assertEqual(self.doc.read_text(), paragraphs(20))

    def test_a_shape_pass_that_cuts_is_refused(self):
        self.write(paragraphs(20))
        self.run_step()
        self.write(paragraphs(19))
        self.run_step()
        self.write(paragraphs(9))
        self.assertIn('Pass 2 removed', text_of(self.run_step()))

    def test_a_pass_that_raises_the_peak_protects_its_new_anchors(self):
        self.write(paragraphs(20))
        self.run_step()
        self.write(paragraphs(20) + '\nThe grammar pass added port 8080 here.\n')
        self.run_step()
        self.write(paragraphs(20) + '\nThe grammar pass added a port here.\n')
        self.assertIn('  8080', self.run_step()[1])

    def test_distilling_the_agents_text_settles_what_it_owed(self):
        self.distill_fresh()
        stamped = self.doc.read_text()
        pending.before_edit('s1', self.doc)
        self.write(stamped + '\n' + paragraphs(6, tag='a'))
        pending.after_edit('s1', self.doc)
        self.assertEqual(sum(pending.owed(self.doc).values()), 60)

        self.run_step('agent')
        shorter = paragraphs(6, tag='a').replace('juliet\n', '\n', 2)  # grammar: 58
        for addition in (shorter, paragraphs(5, tag='a'), paragraphs(3, tag='a')):
            self.write(stamped + '\n' + addition)
            self.run_step()
        self.assertTrue(self.run_step('reviewed')[0])
        self.assertEqual(pending.owed(self.doc), {})

    def test_a_pass_that_drops_an_anchor_is_refused(self):
        self.write(paragraphs(19) + '\nThe server listens on port 3000 by default here.\n')
        self.run_step()
        self.write(paragraphs(19) + '\nThe server listens on a port by default here.\n')
        done, lines = self.run_step()
        self.assertFalse(done)
        self.assertIn('  3000', lines)

    def test_a_typo_fix_in_a_stamped_doc_is_under_the_floor_and_keeps_the_stamp(self):
        self.distill_fresh()
        before = prose.read_stamp(self.doc.read_text())
        self.write(self.doc.read_text().replace('bravo', 'bravvo', 1))
        done, lines = self.run_step()
        self.assertTrue(done)
        self.assertIn('0 new prose words since the stamp', text_of((done, lines)))
        self.assertEqual(prose.read_stamp(self.doc.read_text()), before)

    def test_redistilling_bills_only_the_new_text_and_protects_the_old(self):
        self.distill_fresh()
        stamped = self.doc.read_text()
        self.write(stamped + '\n' + paragraphs(6, tag='n'))
        done, lines = self.run_step()
        self.assertIn('60 prose words to distill (new since the stamp)', text_of((done, lines)))

        old_edited = self.doc.read_text().replace('alphap0', 'omegap0')
        self.write(old_edited)
        self.assertIn('already distilled', text_of(self.run_step()))

    def test_a_stamp_with_no_sidecar_is_trusted_and_starts_an_entry(self):
        self.distill_fresh()
        (self.dir / '.distill.json').unlink()
        done, lines = self.run_step()
        self.assertTrue(done)
        self.assertIn('has no entry for it', text_of((done, lines)))
        self.assertTrue((self.dir / '.distill.json').exists())

    def test_a_doc_that_lost_its_stamp_relinks_by_path(self):
        self.distill_fresh()
        self.write(prose.body(self.doc.read_text()))
        self.assertIn('re-linked', text_of(self.run_step()))

    def user_types(self, output, word):
        """The user replies with the confirmation phrase the script printed for `word`."""
        phrase = re.search(rf'{word} [0-9a-f]{{6}}', output).group(0)
        pending.record_prompt('s1', f'yes, {phrase}')

    def test_a_stop_needs_the_users_phrase_and_the_stamp_says_so(self):
        self.write(paragraphs(20))
        self.run_step()
        self.write(paragraphs(19))
        self.run_step()
        refused = text_of(self.run_step('stop'))
        self.assertNotIn('Next: a blind review', refused)
        self.user_types(refused, 'accept')
        self.assertIn('Next: a blind review', text_of(self.run_step('stop')))
        self.assertTrue(self.run_step('reviewed')[0])
        self.assertTrue(prose.read_stamp(self.doc.read_text())['stopped'])

    def test_a_phrase_the_agent_says_itself_does_not_count(self):
        self.write(paragraphs(20))
        self.run_step()
        refused = text_of(self.run_step('stop'))
        phrase = re.search(r'accept [0-9a-f]{6}', refused).group(0)
        self.write(paragraphs(20) + f'\n{phrase}\n')  # written into the doc, not typed by the user
        self.assertNotIn('Next: a blind review', text_of(self.run_step('stop')))

    def curve(self, *counts, preset=None):
        """Record a curve of word counts, returning the last result."""
        result = None
        for n, count in enumerate(counts):
            self.write(prose_words(count))
            result = self.run_step(preset=preset if n == 0 else None)
        return result

    def test_fluff_passes_that_stop_paying_off_above_the_ceiling_stall(self):
        done, lines = self.curve(200, 195, 190, 182, 175, 168)
        self.assertFalse(done)
        self.assertIn('STALLED', text_of((done, lines)))
        self.assertNotIn('Pass 6', text_of((done, lines)))
        self.assertRegex(text_of((done, lines)), r'accept [0-9a-f]{6}')  # what the user types to accept it

    def test_grammar_and_shape_passes_do_not_count_toward_a_stall(self):
        self.assertNotIn('STALLED', text_of(self.curve(200, 195, 190, 186)))

    def test_the_user_can_pick_a_gentler_preset_for_a_stalled_doc(self):
        stall = text_of(self.curve(200, 195, 190, 182, 175, 168))
        self.assertNotIn('Next: a blind review', text_of(self.run_step(preset='relaxed')))
        self.user_types(stall, 'relaxed')
        self.assertIn('Next: a blind review', text_of(self.run_step(preset='relaxed')))

    def test_the_skill_never_offers_the_agent_dictation(self):
        skill = (ROOT / 'skills' / 'distill' / 'SKILL.md').read_text()
        self.assertNotIn('dictated', skill)

    def test_the_review_question_asks_what_a_reader_cannot_act_without(self):
        self.assertIn('cannot act correctly without', text_of(self.curve(200, 195, 190, 90)))

    def test_restoring_more_than_a_tenth_after_the_review_is_refused(self):
        self.curve(200, 195, 190, 90)
        self.write(prose_words(110))
        self.assertIn('Restoring', text_of(self.run_step('reviewed')))
        self.write(prose_words(95))
        self.assertTrue(self.run_step('reviewed')[0])

    def test_editing_a_code_block_the_agent_wrote_is_not_editing_old_text(self):
        self.distill_fresh()
        stamped = self.doc.read_text()
        addition = '\n' + paragraphs(6, tag='a') + '\n```\nlsof -i :3000\n```\n'
        pending.before_edit('s1', self.doc)
        self.write(stamped + addition)
        pending.after_edit('s1', self.doc)
        self.run_step('agent')
        self.write(stamped + addition.replace('lsof -i :3000', 'lsof -i :3000 -t').replace('juliet', 'kilo', 1))
        self.assertNotIn('already distilled', text_of(self.run_step()))

    def test_the_skill_names_its_base_directory_rather_than_a_shell_fallback(self):
        skill = (ROOT / 'skills' / 'distill' / 'SKILL.md').read_text()
        self.assertNotIn(':-.', skill)
        self.assertIn('base directory', skill)

    def test_the_skill_never_offers_the_agent_a_stop(self):
        skill = (ROOT / 'skills' / 'distill' / 'SKILL.md').read_text()
        self.assertNotIn('--stop', skill)

    def test_a_preset_is_used_and_recorded(self):
        self.write(paragraphs(20))
        self.assertIn('(moderate) at 120', text_of(self.run_step(preset='moderate')))

    def test_an_unclosed_fence_is_refused(self):
        self.write(paragraphs(20) + '```\ncode\n')
        self.assertIn('unclosed', text_of(self.run_step()))

    def test_agent_scope_bills_the_agents_text_and_not_the_humans(self):
        self.distill_fresh()
        stamped = self.doc.read_text()
        self.write(stamped + '\n' + paragraphs(6, tag='h'))  # a human's addition
        pending.before_edit('s1', self.doc)
        self.write(self.doc.read_text() + '\n' + paragraphs(7, tag='a'))  # the agent's
        pending.after_edit('s1', self.doc)
        done, lines = self.run_step('agent')
        self.assertIn('70 prose words to distill', text_of((done, lines)))


class Git(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve()
        self.env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                    'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        self.git('init', '-q')
        self.doc = self.repo / 'AGENTS.md'
        self.store = tempfile.TemporaryDirectory()
        self.saved_store = pending.STORE
        pending.STORE = Path(self.store.name)

    def tearDown(self):
        pending.STORE = self.saved_store
        self.tmp.cleanup()
        self.store.cleanup()

    def git(self, *args):
        subprocess.run(['git', *args], cwd=self.repo, env=self.env, check=True, capture_output=True)

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'x')

    def test_a_tracked_doc_is_measured_against_the_commit_that_carries_its_stamp(self):
        self.doc.write_text(paragraphs(20))
        self.commit()
        for n in (20, 19, 14, 9):
            self.doc.write_text(paragraphs(n))
            distill.step(self.doc)
        done, lines = distill.step(self.doc, 'reviewed')
        self.assertTrue(done)
        self.assertIn('Commit AGENTS.md now', text_of((done, lines)))
        self.assertFalse(any(self.repo.glob('.distill.json')))
        self.commit()

        self.doc.write_text(self.doc.read_text() + '\n' + paragraphs(6, tag='n'))
        self.commit()  # later commits do not move the reference point
        self.assertIn('60 prose words to distill (new since the stamp)', text_of(distill.step(self.doc)))

    def test_a_repo_that_runs_the_gate_gets_the_gate(self):
        (self.repo / 'scripts').mkdir()
        (self.repo / 'scripts' / 'check-docs.mjs').write_text('')
        self.doc.write_text(paragraphs(20))
        self.commit()
        self.assertIn('docs-distillation-gate', text_of(distill.step(self.doc)))


class Cli(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / 'd.md'
            doc.write_text(paragraphs(2))
            script = ROOT / 'skills' / 'distill' / 'scripts' / 'distill.py'
            run = lambda *a: subprocess.run([sys.executable, str(script), *a], capture_output=True, text=True)
            self.assertEqual(run(str(doc)).returncode, 0)  # under the floor
            doc.write_text(paragraphs(20))
            self.assertEqual(run(str(doc)).returncode, 1)
            self.assertEqual(run(str(Path(tmp) / 'missing.md')).returncode, 2)


if __name__ == '__main__':
    unittest.main()
