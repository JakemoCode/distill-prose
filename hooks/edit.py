#!/usr/bin/env python3
"""distill-prose hooks: record what the user says and what an agent writes into a
stamped doc, and gate the Stop.

  edit.py prompt   UserPromptSubmit
  edit.py pre      PreToolUse on Edit|Write
  edit.py post     PostToolUse on Edit|Write
  edit.py stop     Stop

Only docs carrying a distill-prose stamp are watched. Human edits never pass
through these hooks, so they are never billed.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'skills' / 'distill' / 'scripts'))
import distill  # noqa: E402
import pending  # noqa: E402
import prose  # noqa: E402


def watched(doc):
    return (
        doc.suffix.lower() in ('.md', '.markdown')
        and doc.is_file()
        and prose.read_stamp(doc.read_text()) is not None
        # The skill's own passes edit the doc too. They are the distillation.
        and not distill.session_active(doc)
    )


def main():
    event = sys.argv[1]
    data = json.load(sys.stdin)
    session = data.get('session_id') or 'unknown'
    pending.prune()

    if event == 'prompt':
        pending.record_prompt(session, data.get('prompt') or '')
        return

    if event in ('pre', 'post'):
        path = (data.get('tool_input') or {}).get('file_path')
        if not path:
            return
        doc = Path(path).resolve()
        if event == 'pre' and watched(doc):
            pending.before_edit(session, doc)
        elif event == 'post' and doc.is_file() and not distill.session_active(doc):
            pending.after_edit(session, doc)
        return

    debts = [(doc, words) for doc, words in pending.session_debts(session)
             if words >= prose.FLOOR and not distill.session_active(doc)]
    if not debts:
        return
    listing = ', '.join(f'{doc} ({words} words)' for doc, words in debts)

    # Blocking twice would trap a session that cannot distill: a refused
    # command, or no python3. Let it end, and say what is still owed.
    if data.get('stop_hook_active'):
        print(json.dumps({'systemMessage': f'distill-prose: still undistilled: {listing}'}))
        return

    doc, words = debts[0]
    print(json.dumps({
        'decision': 'block',
        'reason': (
            f'You added {words} prose words to {doc}, a distilled doc. Distill your additions before you '
            f'finish: run `{distill.run_line(doc, "--agent")}` and follow what it prints.'
            + (f' Also owed: {listing}.' if len(debts) > 1 else '')
        ),
    }))


if __name__ == '__main__':
    # These hooks run on every prompt and every edit in every session. An error
    # printed there shows up on each one, so a failure skips this one check
    # instead. The Stop gate simply doesn't block that turn.
    try:
        main()
    except Exception:
        pass
