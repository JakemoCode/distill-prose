"""What an agent owes: text it wrote into a stamped doc and has not distilled.

The edit hooks record the owed text. The Stop hook refuses to end a turn over
it, and distill.py settles it. It lives in per-session files in the system temp
directory because the obligation belongs to the session that created it, never
to the repo.
"""

import json
import tempfile
from pathlib import Path

import prose

STORE = Path(tempfile.gettempdir()) / 'distill-prose'


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


def before_edit(session_id, doc):
    """Remember the doc's blocks just before an agent edits it."""
    data = _load(session_id)
    entry = data['docs'].setdefault(str(doc), {'owed': {}, 'dictated': {}})
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
            if share:
                owed[digest] = owed.get(digest, 0) + share
            total -= share
    _save(session_id, data)


def owed(doc):
    """Owed words per block across every session, minus text marked as dictated."""
    merged = {}
    for path in _sessions():
        entry = json.loads(path.read_text())['docs'].get(str(doc))
        if entry:
            for digest, words in entry['owed'].items():
                merged[digest] = merged.get(digest, 0) + words
    return merged


def owed_words(entry, doc):
    present = {b[0] for b in prose.block_list(prose.body(doc.read_text()))}
    return sum(words for digest, words in entry['owed'].items() if digest in present)


def session_debts(session_id):
    """(doc, owed words) for each stamped doc this session still owes a distillation."""
    debts = []
    for name, entry in _load(session_id)['docs'].items():
        doc = Path(name)
        if doc.is_file():
            words = owed_words(entry, doc)
            if words:
                debts.append((doc, words))
    return debts


def mark_dictated(doc):
    """Move the agent's owed text in a doc to dictated: the user's own words."""
    total = 0
    for path in _sessions():
        data = json.loads(path.read_text())
        entry = data['docs'].get(str(doc))
        if entry:
            total += sum(entry['owed'].values())
            entry['dictated'].update(entry['owed'])
            entry['owed'] = {}
            path.write_text(json.dumps(data))
    return total


def note(doc, message):
    """Leave a message for the user in every session that owed text on this doc."""
    for path in _sessions():
        data = json.loads(path.read_text())
        if str(doc) in data['docs']:
            data.setdefault('notes', []).append(message)
            path.write_text(json.dumps(data))


def take_notes(session_id):
    """The session's messages for the user, cleared once read."""
    data = _load(session_id)
    notes = data.pop('notes', [])
    if notes:
        _save(session_id, data)
    return notes


def settle(doc):
    """Forget what every session owed on a doc once it has been distilled."""
    for path in _sessions():
        data = json.loads(path.read_text())
        if data['docs'].pop(str(doc), None) is not None:
            path.write_text(json.dumps(data))
