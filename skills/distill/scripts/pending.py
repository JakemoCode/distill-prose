"""What an agent owes, and what the user said.

The edit hooks record text an agent wrote into a stamped doc. The prompt hook
records what the user typed. The Stop hook refuses to end a turn over owed
text, and distill.py settles it.

The user's own words are the one thing an agent cannot fabricate, so they are
the evidence for every decision that belongs to the user: text the user
dictated is not billed, and a stop or a gentler preset needs a phrase the user
typed.

Everything lives in per-session files in the system temp directory, because it
belongs to the session that created it, never to the repo.
"""

import difflib
import json
import re
import tempfile
from pathlib import Path

import prose

STORE = Path(tempfile.gettempdir()) / 'distill-prose'
PROMPTS_KEPT = 50
DICTATED_SHARE = 0.9  # of a block's words, in order, found in one prompt


def _path(session_id):
    return STORE / f'{session_id}.json'


def _load(session_id):
    path = _path(session_id)
    return json.loads(path.read_text()) if path.exists() else {'docs': {}}


def _save(session_id, data):
    STORE.mkdir(parents=True, exist_ok=True)
    _path(session_id).write_text(json.dumps(data))


def _sessions():
    return sorted(STORE.glob('*.json')) if STORE.exists() else []


# What the user typed ----------------------------------------------------------

def record_prompt(session_id, text):
    data = _load(session_id)
    data['prompts'] = (data.get('prompts', []) + [text])[-PROMPTS_KEPT:]
    _save(session_id, data)


def all_prompts():
    prompts = []
    for path in _sessions():
        prompts.extend(json.loads(path.read_text()).get('prompts', []))
    return prompts


_WORD = re.compile(r'\w+')


def dictated(text, prompts):
    """True when the user typed this block: most of its words, in order, in one prompt.

    Case, whitespace and markdown syntax are ignored, so the agent can set the
    user's words as a list item or fix a word and they stay the user's.
    """
    words = _WORD.findall(text.lower())
    if not words:
        return False
    for prompt in prompts:
        said = _WORD.findall(prompt.lower())
        matcher = difflib.SequenceMatcher(a=words, b=said, autojunk=False)
        if sum(size for _, _, size in matcher.get_matching_blocks()) >= len(words) * DICTATED_SHARE:
            return True
    return False


# What the agent wrote ---------------------------------------------------------

def before_edit(session_id, doc):
    """Remember the doc's blocks just before an agent edits it."""
    data = _load(session_id)
    entry = data['docs'].setdefault(str(doc), {'owed': {}})
    entry['pre'] = prose.block_list(prose.body(doc.read_text()))
    _save(session_id, data)


def after_edit(session_id, doc):
    """Record what the edit added: new blocks in full, edited blocks by their growth."""
    data = _load(session_id)
    entry = data['docs'].get(str(doc))
    if entry is None or 'pre' not in entry:
        return
    old = entry.pop('pre')
    new = prose.block_list(prose.body(doc.read_text()))
    owed = entry['owed']

    for tag, i1, i2, j1, j2 in prose._opcodes(old, new):
        if tag == 'equal':
            continue
        # Text this session already owed moves with the block it lives in, so
        # editing owed text again cannot launder it into old text.
        carried = sum(owed.pop(b[0], 0) for b in old[i1:i2])
        new_words = sum(b[1] for b in new[j1:j2])
        if tag == 'insert':
            total = new_words
        elif tag == 'replace':
            total = max(0, carried + new_words - sum(b[1] for b in old[i1:i2]))
        else:
            total = 0
        for digest, words in new[j1:j2]:
            share = min(words, total)
            # Every block the agent wrote is recorded, a code block with no prose
            # words too. An unrecorded one would count as old, distilled text,
            # and editing it would be refused.
            owed[digest] = owed.get(digest, 0) + share
            total -= share
    _save(session_id, data)


def _agents_blocks(doc, entry, prompts):
    """The owed blocks still in the doc, less the ones the user dictated."""
    texts = {digest: text for digest, _, text in prose.blocks(prose.body(doc.read_text()))}
    return {digest: words for digest, words in entry['owed'].items()
            if digest in texts and not dictated(texts[digest], prompts)}


def owed(doc):
    """Owed words per block across every session, less what each session's user dictated."""
    merged = {}
    for path in _sessions():
        data = json.loads(path.read_text())
        entry = data['docs'].get(str(doc))
        if entry:
            for digest, words in _agents_blocks(doc, entry, data.get('prompts', [])).items():
                merged[digest] = merged.get(digest, 0) + words
    return merged


def session_debts(session_id):
    """(doc, owed words) for each stamped doc this session still owes a distillation."""
    data = _load(session_id)
    debts = []
    for name, entry in data['docs'].items():
        doc = Path(name)
        if doc.is_file():
            words = sum(_agents_blocks(doc, entry, data.get('prompts', [])).values())
            if words:
                debts.append((doc, words))
    return debts


def settle(doc):
    """Forget what every session owed on a doc once it has been distilled."""
    for path in _sessions():
        data = json.loads(path.read_text())
        if data['docs'].pop(str(doc), None) is not None:
            path.write_text(json.dumps(data))
