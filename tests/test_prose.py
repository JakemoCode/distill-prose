import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'skills' / 'distill' / 'scripts'))
import prose  # noqa: E402

FIXTURES = ROOT / 'fixtures' / 'counting'


class SharedFixtures(unittest.TestCase):
    """The cases docs-distillation-gate's counter must agree on too."""

    expected = json.loads((FIXTURES / 'expected.json').read_text())

    def test_every_fixture_doc_counts_as_the_gate_counts_it(self):
        for name, want in self.expected['docs'].items():
            with self.subTest(name):
                text = (FIXTURES / name).read_text()
                self.assertEqual(prose.count_words(text), (want['prose'], want['hidden']))
                self.assertEqual(prose.fences_balance(text), want['balanced'])

    def test_every_fixture_curve_gets_the_gates_verdict(self):
        for case in self.expected['curves']:
            with self.subTest(case['counts']):
                self.assertEqual(prose.verdict(case['counts']), (case['pass'], case['reason']))


class Presets(unittest.TestCase):
    def test_moderate_passes_at_sixty_percent(self):
        self.assertEqual(prose.verdict([200, 120], 'moderate'), (True, 'target'))
        self.assertEqual(prose.verdict([200, 120], 'aggressive'), (False, 'blocked'))

    def test_relaxed_converges_under_its_higher_ceiling(self):
        curve = [200, 180, 172, 168, 165]
        self.assertEqual(prose.verdict(curve, 'relaxed'), (True, 'converged'))
        self.assertEqual(prose.verdict(curve, 'moderate'), (False, 'blocked'))


class Stamps(unittest.TestCase):
    def test_a_stamp_round_trips(self):
        line = prose.format_stamp('a1b2c3', 'moderate', 539, 310)
        stamp = prose.read_stamp(f'{line}\n# Title\n')
        self.assertEqual((stamp['id'], stamp['preset'], stamp['curve'], stamp['stopped']),
                         ('a1b2c3', 'moderate', [539, 310], False))

    def test_the_stamp_goes_after_frontmatter(self):
        text = '---\nname: x\n---\nBody.\n'
        stamped = prose.write_stamp(text, prose.format_stamp('a1b2c3', 'aggressive', 100, 50, True))
        self.assertEqual(stamped.split('\n')[3], '<!-- distill-prose a1b2c3 aggressive 100->50 stopped -->')
        self.assertIsNotNone(prose.read_stamp(stamped))

    def test_restamping_replaces_the_old_stamp(self):
        once = prose.write_stamp('Body.\n', prose.format_stamp('a1b2c3', 'aggressive', 100, 50))
        twice = prose.write_stamp(once, prose.format_stamp('a1b2c3', 'aggressive', 80, 40))
        self.assertEqual(twice.count('distill-prose'), 1)
        self.assertEqual(prose.body(twice), 'Body.\n')


class Billing(unittest.TestCase):
    doc = '# Guide\n\nThe first paragraph has exactly eight words here.\n\n- one item\n- two item\n'

    def test_a_typo_fix_bills_nothing(self):
        fixed = self.doc.replace('exactly', 'exaktly')
        self.assertEqual(prose.billed(prose.block_list(self.doc), prose.block_list(fixed)), 0)

    def test_an_added_sentence_bills_only_the_sentence(self):
        grown = self.doc.replace('here.', 'here. Four more words.')
        self.assertEqual(prose.billed(prose.block_list(self.doc), prose.block_list(grown)), 3)

    def test_a_new_paragraph_bills_in_full(self):
        grown = self.doc + '\nA brand new paragraph of seven words.\n'
        self.assertEqual(prose.billed(prose.block_list(self.doc), prose.block_list(grown)), 7)

    def test_a_fresh_doc_bills_every_prose_word(self):
        self.assertEqual(prose.billed([], prose.block_list(self.doc)), prose.count_words(self.doc)[0])

    def test_a_fenced_block_with_blank_lines_is_one_block(self):
        text = 'Intro.\n\n```\na\n\nb\n```\n\nOutro.\n'
        self.assertEqual(len(prose.blocks(text)), 3)


class Anchors(unittest.TestCase):
    text = ('Set `SESSION_SECRET` to 32 characters. NEVER commit .env files.\n'
            'Run npm run dev on port 3000, see https://example.com/docs and docs/setup.md, Node v20.1.\n')

    def test_anchors_are_code_identifiers_numbers_urls_paths_and_emphasis(self):
        found = prose.anchors([self.text])
        for anchor in ('`SESSION_SECRET`', '32', 'NEVER', '3000', 'https://example.com/docs',
                       'docs/setup.md', 'v20.1'):
            self.assertIn(anchor, found)

    def test_a_dropped_number_is_missing_and_a_longer_number_does_not_hide_it(self):
        found = prose.anchors([self.text])
        cut = self.text.replace('port 3000', 'port 30001')
        self.assertIn('3000', prose.missing_anchors(found, cut))

    def test_rewording_around_anchors_keeps_them(self):
        found = prose.anchors([self.text])
        reworded = ('NEVER commit .env files. `SESSION_SECRET` needs 32 characters. '
                    'Start with npm run dev (port 3000). Docs: https://example.com/docs, docs/setup.md. Node v20.1.')
        self.assertEqual(prose.missing_anchors(found, reworded), [])

    def test_list_numbering_is_not_an_anchor(self):
        self.assertNotIn('1', prose.anchors(['1. First step']))


if __name__ == '__main__':
    unittest.main()
