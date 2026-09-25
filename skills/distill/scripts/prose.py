"""Counting, blocks, billing, anchors and stamps for distill-prose.

Word counting is a port of docs-distillation-gate's check-docs.mjs. The two
implementations must agree on every case in fixtures/counting, which is the
only thing keeping them from drifting apart.
"""

import difflib
import hashlib
import re

# Target and converged ceiling, as shares of the peak. Aggressive is the gate's
# own pair, so a doc distilled with no preset passes the gate too.
PRESETS = {
    'aggressive': (0.50, 0.65),
    'moderate': (0.60, 0.75),
    'relaxed': (0.70, 0.85),
}
DEFAULT_PRESET = 'aggressive'

WEAK_PASS_RATIO = 0.05  # a pass removing less than this is weak
WEAK_PASSES_TO_CONVERGE = 2  # two, so one weak pass cannot stop early
MINIMUM_PASSES = 3
FLOOR = 50  # below this many prose words there is nothing to distill
PARKED_SHARE = 0.5
PARKED_FLOOR = 20

_SYNTAX = re.compile(r'[#*_>\-|]+')
_LETTER = re.compile(r'[A-Za-z]')
_INLINE_CODE = re.compile(r'`[^`]*`')


def _tokens(text):
    return sum(1 for token in _SYNTAX.sub(' ', text).split() if _LETTER.search(token))


def count_words(text):
    """(prose, hidden): what a reader reads, and words kept out of that count."""
    prose = 0
    hidden = 0
    fenced = False
    for line in text.split('\n'):
        if line.lstrip().startswith('```'):
            fenced = not fenced
            continue
        trimmed = line.strip()
        if fenced or trimmed.startswith('<!--'):
            hidden += _tokens(trimmed)
            continue
        hidden += sum(_tokens(span[1:-1]) for span in _INLINE_CODE.findall(trimmed))
        prose += _tokens(_INLINE_CODE.sub(' ', trimmed))
    return prose, hidden


def fences_balance(text):
    return sum(1 for line in text.split('\n') if line.lstrip().startswith('```')) % 2 == 0


def verdict(counts, preset=DEFAULT_PRESET):
    """(passed, reason) for a curve whose first count is the peak."""
    target, ceiling = PRESETS[preset]
    baseline, current = counts[0], counts[-1]
    if baseline < FLOOR:
        return True, 'floor'
    if current <= baseline * target:
        return True, 'target'
    # A count of zero has no share to remove. Emptying a doc and refilling it is
    # a rewrite, and reading it as a weak pass would let two of them converge.
    removals = [1 if start == 0 else (start - end) / start for start, end in zip(counts, counts[1:])]
    converged = (
        len(removals) >= MINIMUM_PASSES
        and all(share < WEAK_PASS_RATIO for share in removals[-WEAK_PASSES_TO_CONVERGE:])
        and current <= baseline * ceiling
    )
    return (True, 'converged') if converged else (False, 'blocked')


def curve_of(counts):
    """The peak, then every later count, with repeats collapsed."""
    peak = counts.index(max(counts))
    curve = []
    for count in counts[peak:]:
        if not curve or curve[-1] != count:
            curve.append(count)
    return curve


# Stamps -------------------------------------------------------------------

STAMP = re.compile(
    r'^<!-- distill-prose (?P<id>[0-9a-f]+) (?P<preset>aggressive|moderate|relaxed) '
    r'(?P<peak>\d+)->(?P<final>\d+)(?P<stopped> stopped)? -->$'
)
GATE_STAMP = re.compile(r'^<!-- distilled: ')


def _frontmatter_end(lines):
    """Index of the first line after YAML frontmatter, or 0 when there is none."""
    if lines and lines[0].strip() == '---':
        for index in range(1, len(lines)):
            if lines[index].strip() == '---':
                return index + 1
    return 0


def read_stamp(text):
    """The stamp's fields, or None. It sits on the first non-blank line after frontmatter."""
    lines = text.split('\n')
    for line in lines[_frontmatter_end(lines):]:
        if line.strip():
            found = STAMP.match(line.strip())
            if not found:
                return None
            return {
                'id': found['id'],
                'preset': found['preset'],
                'curve': [int(found['peak']), int(found['final'])],
                'stopped': bool(found['stopped']),
                'line': line.strip(),
            }
    return None


def format_stamp(stamp_id, preset, peak, final, stopped=False):
    return f"<!-- distill-prose {stamp_id} {preset} {peak}->{final}{' stopped' if stopped else ''} -->"


def body(text):
    """The doc without its stamp line."""
    stamp = read_stamp(text)
    if stamp is None:
        return text
    lines = text.split('\n')
    index = lines.index(next(line for line in lines if line.strip() == stamp['line']))
    return '\n'.join(lines[:index] + lines[index + 1:])


def write_stamp(text, stamp_line):
    """Put the stamp on the first line after frontmatter, replacing any old one."""
    lines = body(text).split('\n')
    at = _frontmatter_end(lines)
    return '\n'.join(lines[:at] + [stamp_line] + lines[at:])


# Blocks -------------------------------------------------------------------

_LIST_ITEM = re.compile(r'^\s*([-*+]|\d+[.)])\s')


def _block(lines):
    text = '\n'.join(line.rstrip() for line in lines).strip('\n')
    digest = hashlib.sha1(text.encode()).hexdigest()[:8]
    return (digest, count_words(text)[0], text)


def blocks(text):
    """Split a doc into (hash, prose words, text) per paragraph, list item,
    table row, heading, frontmatter and fenced block.

    Blocks are the unit of billing: text the old version did not have shows up
    as blocks the old block list does not contain.
    """
    lines = text.split('\n')
    result = []
    current = []
    kind = None

    def flush():
        nonlocal current, kind
        if current:
            result.append(_block(current))
        current, kind = [], None

    index = _frontmatter_end(lines)
    if index:
        result.append(_block(lines[:index]))

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith('```'):
            flush()
            fence = [line]
            index += 1
            while index < len(lines):
                fence.append(lines[index])
                if lines[index].strip().startswith('```'):
                    break
                index += 1
            result.append(_block(fence))
        elif not stripped:
            flush()
        elif stripped.startswith('#') or stripped.startswith('|'):
            flush()
            result.append(_block([line]))
        elif _LIST_ITEM.match(line):
            flush()
            current, kind = [line], 'item'
        else:
            if kind is None:
                kind = 'paragraph'
            current.append(line)
        index += 1
    flush()
    return result


def block_list(text):
    """(hash, words) pairs: all that billing needs, and all a sidecar stores."""
    return [[digest, words] for digest, words, _ in blocks(text)]


def _opcodes(old, new):
    matcher = difflib.SequenceMatcher(a=[b[0] for b in old], b=[b[0] for b in new], autojunk=False)
    return matcher.get_opcodes()


def billed(old, new):
    """Prose words in `new` that `old` did not have.

    A block that is entirely new is billed in full. A block that was edited is
    billed only for its growth, so fixing a typo costs nothing and adding a
    sentence costs the sentence.
    """
    total = 0
    for tag, i1, i2, j1, j2 in _opcodes(old, new):
        if tag == 'insert':
            total += sum(b[1] for b in new[j1:j2])
        elif tag == 'replace':
            total += max(0, sum(b[1] for b in new[j1:j2]) - sum(b[1] for b in old[i1:i2]))
    return total


def unchanged(old, new):
    """Hashes of the blocks `new` carries over from `old` untouched."""
    kept = []
    for tag, i1, i2, _, _ in _opcodes(old, new):
        if tag == 'equal':
            kept.extend(b[0] for b in old[i1:i2])
    return kept


def changed_blocks(old, new):
    """The blocks of `new`, with text, that are new or edited relative to `old`."""
    found = []
    for tag, _, _, j1, j2 in _opcodes(old, new):
        if tag in ('insert', 'replace'):
            found.extend(new[j1:j2])
    return found


# Anchors ------------------------------------------------------------------

# Everything a pass can lose that an exact match can check: code, commands,
# identifiers, emphasis, URLs, paths, versions and numbers.
_ANCHORS = [
    re.compile(r'`[^`\n]+`'),
    re.compile(r'https?://[^\s)>\]]*[^\s)>\].,;:!?]'),  # a sentence's closing period is not the URL's
    re.compile(r'\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b'),
    re.compile(r'\b[A-Z]{2,}\b'),
    re.compile(r'(?:[\w.-]+/)+[\w.-]+'),
    re.compile(r'(?<![\w.])v?\d+(?:\.\d+)+\b'),
    re.compile(r'(?<![\w.])\d+(?:\.\d+)?%?(?![\w]|\.\d)'),  # a number can end a sentence
]
_SPACE = re.compile(r'\s+')


def _squash(text):
    return _SPACE.sub(' ', text).strip()


def anchors(block_texts):
    """The exact-match facts in some blocks: their code, identifiers and numbers."""
    found = set()
    for text in block_texts:
        if text.lstrip().startswith('```'):
            found.add(_squash('\n'.join(text.split('\n')[1:-1])))
            continue
        for line in text.split('\n'):
            line = _LIST_ITEM.sub(' ', line)
            for pattern in _ANCHORS:
                found.update(match.group(0) for match in pattern.finditer(line))
    found.discard('')
    return sorted(found)


def invented(block_texts, draft):
    """Anchors in these blocks that the draft never had.

    Code is compared by its text, a code block line by line, so setting the
    draft's own commands in backticks or a fenced block is not invention.
    """
    keys = set()
    for text in block_texts:
        if text.lstrip().startswith('```'):
            keys.update(_squash(line) for line in text.split('\n')[1:-1] if line.strip())
        else:
            keys.update(anchor.strip('`') for anchor in anchors([text]))
    keys.discard('')
    flat = _squash(draft)
    made_up = []
    for key in sorted(keys):
        if re.fullmatch(r'v?\d+(?:\.\d+)*%?', key):
            # Only the digits have to match. The draft may have written them as
            # "300s" or "v20.1", and a longer number such as 3000 does not count.
            digits = re.escape(key.lstrip('v').rstrip('%'))
            if not re.search(rf'(?<![\d.]){digits}(?!\d|\.\d)', flat):
                made_up.append(key)
        elif key not in flat:
            made_up.append(key)
    return made_up


def missing_anchors(anchor_list, text):
    """The anchors a doc no longer contains."""
    flat = _squash(text)
    missing = []
    for anchor in anchor_list:
        if re.fullmatch(r'v?\d+(?:\.\d+)*%?', anchor):
            if not re.search(rf'(?<![\w.]){re.escape(anchor)}(?![\w])', flat):
                missing.append(anchor)
        elif anchor not in flat:
            missing.append(anchor)
    return missing
