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


class Curves(unittest.TestCase):
    def test_the_curve_starts_at_the_peak_and_collapses_repeats(self):
        self.assertEqual(prose.curve_of([180, 200, 150, 150, 140]), [200, 150, 140])


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

    def test_a_url_ends_before_the_sentence_does(self):
        self.assertIn('http://localhost:3000', prose.anchors(['Open http://localhost:3000.']))
        self.assertNotIn('http://localhost:3000.', prose.anchors(['Open http://localhost:3000.']))

    def test_invented_finds_numbers_and_commands_the_draft_never_had(self):
        draft = 'Run npm run dev. The server listens on port 3000.'
        self.assertEqual(prose.invented(['It also listens on 8080.'], draft), ['8080'])
        self.assertEqual(prose.invented(['```\nnpm run build\n```'], draft), ['npm run build'])

    def test_putting_the_drafts_commands_in_code_is_not_invention(self):
        draft = 'Run npm run dev to start the server on port 3000.'
        current = ['Run `npm run dev`.', '```\nnpm run dev\n```', 'It uses port 3000.']
        self.assertEqual(prose.invented(current, draft), [])

    def test_a_code_block_of_the_drafts_commands_is_checked_line_by_line(self):
        draft = 'Run npm install, then npm run migrate.'
        self.assertEqual(prose.invented(['```\nnpm install\nnpm run migrate\n```'], draft), [])

    def test_a_draft_number_written_with_a_unit_or_prefix_is_not_invention(self):
        self.assertEqual(prose.invented(['Wait 300 seconds.'], 'Wait 5 minutes (300s).'), [])
        self.assertEqual(prose.invented(['Install Node 20.1.'], 'Install Node v20.1.'), [])

    def test_a_longer_number_does_not_hide_an_invented_one(self):
        self.assertEqual(prose.invented(['Port 300.'], 'Port 3000.'), ['300'])

    def test_list_numbering_is_not_an_anchor(self):
        self.assertNotIn('1', prose.anchors(['1. First step']))


if __name__ == '__main__':
    unittest.main()
