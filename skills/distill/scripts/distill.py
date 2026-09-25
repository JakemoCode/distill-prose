#!/usr/bin/env python3
"""Distill one markdown doc in measured passes.

Run it before the first edit and after every pass. Its output is the next
instruction. Exit 0 means DONE and nothing else does.

  distill.py <doc> [aggressive|moderate|relaxed]   or --preset <name>
  distill.py <doc> --reviewed   the blind review is done
  distill.py <doc> --stop       the user replied with the accept phrase
  distill.py <doc> --undo       restore the last recorded version
  distill.py <doc> --agent      bill only text this agent wrote (the Stop hook's request)
  distill.py <doc> --reset      forget the session
"""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pending  # noqa: E402
import prose  # noqa: E402

SCRATCH = '.distill'
SIDECAR = '.distill.json'
GRAMMAR_FLOOR = 0.90  # a grammar pass keeps at least this share of the count
SHAPE_FLOOR = 0.70  # a shape pass reorganizes; it removes connective words at most
STALL_ATTEMPTS = 5  # attempts in a row that were refused or cut under the weak-pass share
RESTORE_ALLOWANCE = 0.10  # how far restorations after the review may raise the count

SCRIPT = Path(__file__).resolve()


# Where things live ---------------------------------------------------------

def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)


def repo_root(doc):
    try:
        found = git(doc.parent, 'rev-parse', '--show-toplevel')
    except FileNotFoundError:
        return None  # no git at all
    return Path(found.stdout.strip()).resolve() if found.returncode == 0 else None


def is_tracked(root, doc):
    return root is not None and git(root, 'ls-files', '--error-unmatch', '--', str(doc)).returncode == 0


def session_dir(doc):
    """Scratch for one doc's session: the repo root when there is one, else the doc's folder."""
    root = repo_root(doc) or doc.parent
    slug = str(doc.relative_to(root)).replace(os.sep, '__')
    return root / SCRATCH / slug, root


def session_active(doc):
    return (session_dir(doc)[0] / 'state.json').exists()


def gate_runs_here(root):
    return root is not None and any(
        (root / path).exists() for path in ('scripts/check-docs.mjs', 'check-docs.mjs')
    )


# The sidecar, for docs git does not track ----------------------------------

def load_sidecar(folder):
    path = folder / SIDECAR
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_sidecar(folder, entries):
    # One block per line and sorted keys, so two branches that distil different
    # docs touch different lines and git merges them.
    out = ['{']
    keys = sorted(entries)
    for n, key in enumerate(keys):
        entry = entries[key]
        out.append(f'  {json.dumps(key)}: {{')
        for field in ('path', 'preset', 'curve', 'stopped'):
            out.append(f'    {json.dumps(field)}: {json.dumps(entry[field])},')
        out.append('    "blocks": [')
        rows = [f'      {json.dumps(block)}' for block in entry['blocks']]
        out.append(',\n'.join(rows))
        out.append('    ]')
        out.append('  },' if n < len(keys) - 1 else '  }')
    out.append('}')
    (folder / SIDECAR).write_text('\n'.join(line for line in out if line) + '\n')


# The reference: what the doc looked like when it was last distilled --------

def stamp_commit_text(root, doc, stamp_line):
    """The doc as it was committed with this stamp, or None."""
    found = git(root, 'log', '-S', stamp_line, '--format=%H', '--name-only', '-n', '1')
    lines = [line for line in found.stdout.split('\n') if line.strip()]
    if found.returncode != 0 or not lines:
        return None
    sha, paths = lines[0], lines[1:]
    for path in paths:
        shown = git(root, 'show', f'{sha}:{path}')
        if shown.returncode == 0 and stamp_line in shown.stdout:
            return shown.stdout
    return None


def reference(doc, text, root, tracked):
    """(blocks, stamp id, notice) for the version new text is measured against."""
    stamp = prose.read_stamp(text)
    current = prose.block_list(prose.body(text))

    if tracked:
        if stamp is None:
            return [], None, None
        old = stamp_commit_text(root, doc, stamp['line'])
        if old is None:
            return current, stamp['id'], (
                f"No commit carries this doc's stamp ({stamp['id']}), so there is no history to "
                'measure against. Trusting the stamp: the doc as it stands is the new reference.'
            )
        return prose.block_list(prose.body(old)), stamp['id'], None

    entries = load_sidecar(doc.parent)
    if stamp is not None:
        entry = entries.get(stamp['id'])
        if entry is None:
            return current, stamp['id'], (
                f"{doc.name} carries stamp {stamp['id']} but {doc.parent / SIDECAR} has no entry for it. "
                'Was it copied from another folder? If that folder still has its .distill.json, the user '
                'can copy the entry over. Trusting the stamp for now: the doc as it stands is the new reference.'
            )
        return entry['blocks'], stamp['id'], None

    # A stamp can be deleted by hand. The sidecar still knows the doc by path.
    for stamp_id, entry in entries.items():
        if entry['path'] == doc.name:
            return entry['blocks'], stamp_id, f'{doc.name} lost its stamp line; re-linked it to entry {stamp_id} by path.'
    return [], None, None


def agent_reference(current, owed):
    """The doc with the agent's text taken back out, so only that text is billed.

    A block the agent grew stands in at its size before the agent touched it.
    """
    return [
        [f'~{digest}', max(0, words - owed[digest])] if digest in owed else [digest, words]
        for digest, words in current
    ]


# Instructions ---------------------------------------------------------------

def phase_instruction(number, scoped):
    where = 'the new text' if scoped else 'the doc'
    keep = ('Keep every fact, instruction, number, constraint, reason for a rule, example, '
            'and piece of deliberate emphasis.')
    if number == 1:
        return (f'Pass 1 (grammar): rewrite {where} in ASD-STE100 Simplified Technical English. '
                f'Change grammar only; the count may rise. {keep}')
    if number == 2:
        return (f'Pass 2 (shape): where the content allows, turn {where} into a procedure, a table, '
                f'or a list. Reorganize; do not delete. {keep}')
    return (f'Pass {number} (fluff): read every paragraph of {where}. Cut restated context, duplicate '
            'sections, summaries of what the doc just said, and arguments another doc already makes. '
            f'{keep} The pass ends when you have read all of {where}.')


def exits(peak, preset):
    target, ceiling = prose.PRESETS[preset]
    return (f'It is distilled ({preset}) at {int(peak * target)} prose words or fewer, or when it '
            f'converges: {prose.MINIMUM_PASSES}+ passes, the last {prose.WEAK_PASSES_TO_CONVERGE} each '
            f'removing under {int(prose.WEAK_PASS_RATIO * 100)}%, ending at {int(peak * ceiling)} or fewer.')


def human_at_terminal():
    """A person running the script by hand. An agent's shell has no terminal on stdin."""
    return os.isatty(0)


def user_named(word):
    """True when the user typed this word this session, or is running the script by hand."""
    pattern = re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)
    return human_at_terminal() or any(pattern.search(prompt) for prompt in pending.all_prompts())


def preset_refusal(preset):
    return [f'Only the user picks a preset. Ask them which one they want. The script accepts {preset} '
            f'once they have typed the word "{preset}".', 'Nothing was recorded.']


def phrase(state, word):
    """The reply that proves `word` is the user's decision: only the user can type it."""
    state.setdefault('confirm', secrets.token_hex(3))
    return f"{word} {state['confirm']}"


def user_said(state, word):
    wanted = phrase(state, word)
    return any(wanted in prompt for prompt in pending.all_prompts())


def ask_user(doc, state, word, flag, what):
    return [f'Only the user can {what}. Ask them to reply with `{phrase(state, word)}` if they want that, '
            f'then run: {run_line(doc, flag)}',
            'Nothing was recorded.']


def close(folder):
    """Remove a finished session's scratch, and the scratch folder once no session is left in it."""
    shutil.rmtree(folder)
    scratch = folder.parent
    if all(entry.name == '.gitignore' for entry in scratch.iterdir()):
        shutil.rmtree(scratch)


def stall(doc, folder, state):
    """End a session that has stopped getting anywhere, and release the agent from it.

    Nothing is stamped: text that never got cut stays new since the stamp, so the
    user can ask for it again with a gentler preset.
    """
    curve = prose.curve_of(state['points'])
    target = prose.PRESETS[state['preset']][0]
    gentler = [name for name, (share, _) in prose.PRESETS.items() if share > target]
    pending.settle(doc)
    close(folder)
    return [
        f'STALLED: {STALL_ATTEMPTS} attempts in a row made no progress. Each was refused or cut under '
        f'{int(prose.WEAK_PASS_RATIO * 100)}%. Curve: {" -> ".join(map(str, curve))} prose words. '
        f'This text resists cutting at {state["preset"]}.',
        'The session is over. Nothing was stamped, and you owe nothing more on this doc.',
        'Tell the user the curve and end your turn. They can ask for a gentler preset'
        + (f' ({" or ".join(gentler)})' if gentler else '') + ', or to accept the text as it stands.',
    ]


def no_progress(doc, folder, root, state, lines):
    """Count an attempt that got nowhere. Enough of them in a row end the session."""
    state['fruitless'] = state.get('fruitless', 0) + 1
    if state['fruitless'] >= STALL_ATTEMPTS:
        return False, lines + stall(doc, folder, state)
    save_state(folder, root, state)
    return False, lines


def run_line(doc, flag=''):
    return f'python3 "{SCRIPT}" "{doc}"{" " + flag if flag else ""}'


# The session ----------------------------------------------------------------

def load_state(folder):
    path = folder / 'state.json'
    return json.loads(path.read_text()) if path.exists() else None


def save_state(folder, root, state):
    folder.mkdir(parents=True, exist_ok=True)
    # Session scratch belongs to nobody's history. Ignoring it from inside keeps
    # it out of every diff without touching the repo's own .gitignore.
    (root / SCRATCH / '.gitignore').write_text('*\n')
    (folder / 'state.json').write_text(json.dumps(state, indent=2) + '\n')


def start(doc, text, preset, agent_only):
    if preset and preset != prose.DEFAULT_PRESET and not user_named(preset):
        return False, preset_refusal(preset)
    folder, root = session_dir(doc)
    repo = repo_root(doc)
    tracked = is_tracked(repo, doc)
    lines = []

    if tracked and gate_runs_here(repo):
        return False, [
            'This repo runs docs-distillation-gate, and the gate is the referee here.',
            'Distill with its method: commit each pass, then run `node scripts/check-docs.mjs --summary` '
            'and do what it prints.',
        ]

    stamp = prose.read_stamp(text)
    current = prose.block_list(prose.body(text))
    ref, stamp_id, notice = reference(doc, text, repo, tracked)
    if notice:
        lines.append(notice)

    if agent_only:
        owed = pending.owed(doc)
        ref = agent_reference(current, owed)

    chosen = preset or (stamp['preset'] if stamp else prose.DEFAULT_PRESET)
    count = prose.billed(ref, current)
    fresh = stamp is None and stamp_id is None

    if count < prose.FLOOR:
        if not fresh and not tracked and stamp is not None and stamp['id'] not in load_sidecar(doc.parent):
            # A stamp with no entry is trusted: start the entry from the doc as it stands.
            entries = load_sidecar(doc.parent)
            entries[stamp['id']] = {'path': doc.name, 'preset': stamp['preset'], 'curve': stamp['curve'],
                                    'stopped': stamp['stopped'], 'blocks': current}
            save_sidecar(doc.parent, entries)
            lines.append(f'Started a {SIDECAR} entry for {stamp["id"]}.')
        what = 'new prose words since the stamp' if not fresh else 'prose words'
        lines.append(f'DONE. {doc.name} has {count} {what}, under the floor of {prose.FLOOR}. '
                     'Nothing to distill, and the stamp stays where it is.')
        if agent_only:
            pending.settle(doc)
        return True, lines

    new_blocks = prose.changed_blocks(ref, prose.blocks(prose.body(text)))
    state = {
        'doc': str(doc),
        'preset': chosen,
        'stamp_id': stamp_id or secrets.token_hex(3),
        'tracked': tracked,
        'agent_only': agent_only,
        'reference': ref,
        'protected': prose.unchanged(ref, current) if ref else [],
        'anchors': prose.anchors(block[2] for block in new_blocks),
        'points': [count],
        'peak_hidden': prose.count_words(text)[1],
        'reviewed_at': None,
        'stopped': False,
    }
    save_state(folder, root, state)
    (folder / 'peak.md').write_text(text)
    (folder / 'last.md').write_text(text)

    scoped = bool(ref)
    lines += [
        f'Recorded {doc.name}: {count} prose words to distill{" (new since the stamp)" if scoped else ""}. This is the peak.',
        exits(count, chosen),
    ]
    if scoped:
        lines.append('Edit only the new text. Text that was already distilled stays as it is.')
    lines += [phase_instruction(1, scoped), f'Then run: {run_line(doc)}']
    return False, lines


def finish(doc, text, state, folder, curve, reason):
    stamp_line = prose.format_stamp(state['stamp_id'], state['preset'], curve[0], curve[-1], state['stopped'])
    stamped = prose.write_stamp(text, stamp_line)
    doc.write_text(stamped)

    if state['tracked']:
        tail = f'Commit {doc.name} now. The stamp is only a reference point once a commit carries it.'
    else:
        entries = load_sidecar(doc.parent)
        entries[state['stamp_id']] = {
            'path': doc.name,
            'preset': state['preset'],
            'curve': [curve[0], curve[-1]],
            'stopped': state['stopped'],
            'blocks': prose.block_list(prose.body(stamped)),
        }
        save_sidecar(doc.parent, entries)
        tail = f'Recorded it in {doc.parent / SIDECAR}.'

    pending.settle(doc)
    close(folder)
    percent = f'{curve[-1] / curve[0] * 100:.1f}%'
    return [f'DONE. {doc.name} distilled ({reason}): {"->".join(map(str, curve))} ({percent}). {tail}',
            f'Stamp: {stamp_line}']


def step(doc, flag=None, preset=None):
    """Record the doc's state and return (done, lines to print)."""
    doc = doc.resolve()
    folder, root = session_dir(doc)
    state = load_state(folder)

    if flag == 'reset':
        shutil.rmtree(folder, ignore_errors=True)
        return False, [f'Forgot the session for {doc.name}. Run this again to start over.']

    if flag == 'undo':
        if state is None:
            return False, ['There is no session to undo.']
        doc.write_text((folder / 'last.md').read_text())
        return False, [f'Restored {doc.name} to the last recorded version. Redo the pass, then run: {run_line(doc)}']

    text = doc.read_text()
    if not prose.fences_balance(text):
        return False, [f'{doc.name} has an unclosed ``` fence, so nothing after it counts as prose. '
                       'Close it, then run this again. Nothing was recorded.']

    if state is None:
        done, lines = start(doc, text, preset, flag == 'agent')
        state = load_state(folder)
        # A stop can come after a stall ended the session. It starts a new one
        # and still needs the user's phrase.
        if flag != 'stop' or state is None:
            return done, lines

    current = prose.block_list(prose.body(text))
    lines = []

    lost_old = [h for h in state['protected'] if h not in {b[0] for b in current}]
    if lost_old:
        return no_progress(doc, folder, root, state, [f'This pass changed {len(lost_old)} block(s) of text that was already distilled. '
                       'Only the new text is being distilled.',
                       f'Put the old text back (`{run_line(doc, "--undo")}` restores the last recorded version), '
                       'then run this again. Nothing was recorded.'])

    missing = prose.missing_anchors(state['anchors'], prose.body(text))
    if missing:
        return no_progress(doc, folder, root, state, [
            'These are gone from the doc, and every one of them has to survive:',
            *[f'  {anchor}' for anchor in missing],
            f'Put them back (or `{run_line(doc, "--undo")}`), then run this again. Nothing was recorded.'])

    count = prose.billed(state['reference'], current)
    points = state['points']
    passes = len(points) - 1

    if flag == 'stop' and not user_said(state, 'accept'):
        save_state(folder, root, state)
        return False, ask_user(doc, state, 'accept', '--stop', f'stop a distillation and accept {doc.name} as it stands')

    if preset and preset != state['preset']:
        if not user_named(preset):
            return False, preset_refusal(preset)
        state['preset'] = preset

    asked = state.get('review_asked_at')
    if asked is not None and count > asked * (1 + RESTORE_ALLOWANCE):
        return no_progress(doc, folder, root, state, [f'Restoring took the doc from {asked} to {count} prose words, more than '
                       f'{int(RESTORE_ALLOWANCE * 100)}% above the reviewed version. Restore only what a reader '
                       'cannot act correctly without, then run this again. Nothing was recorded.'])

    if count != points[-1]:
        if passes == 0 and count < points[0] * GRAMMAR_FLOOR:
            return no_progress(doc, folder, root, state, [f'Pass 1 removed {(1 - count / points[0]) * 100:.0f}% of the prose. The grammar pass '
                           'changes grammar only; cutting comes later, once the grammar shows what is empty.',
                           f'Run `{run_line(doc, "--undo")}` and redo pass 1. Nothing was recorded.'])
        if passes == 1 and count < points[-1] * SHAPE_FLOOR:
            return no_progress(doc, folder, root, state, [f'Pass 2 removed {(1 - count / points[-1]) * 100:.0f}%. The shape pass reorganizes '
                           'into a procedure, table or list; it does not cut.',
                           f'Run `{run_line(doc, "--undo")}` and redo pass 2. Nothing was recorded.'])
        # Grammar and shape passes are not meant to cut, so any valid one is
        # progress. After them, progress is a new low by the weak-pass share.
        if passes < 2 or count <= min(points) * (1 - prose.WEAK_PASS_RATIO):
            state['fruitless'] = 0
        else:
            state['fruitless'] = state.get('fruitless', 0) + 1
        points.append(count)
        (folder / 'last.md').write_text(text)
        if count > max(points[:-1]):
            (folder / 'peak.md').write_text(text)
            state['peak_hidden'] = prose.count_words(text)[1]
            new_blocks = prose.changed_blocks(state['reference'], prose.blocks(prose.body(text)))
            state['anchors'] = prose.anchors(block[2] for block in new_blocks)
    elif flag not in ('reviewed', 'stop'):
        lines.append('The prose count has not changed since the last run, so no pass was recorded.')

    if flag == 'stop':
        state['stopped'] = True

    curve = prose.curve_of(points)
    passes = len(curve) - 1
    passed, reason = prose.verdict(curve, state['preset'])
    if state['stopped']:
        passed, reason = True, 'stopped by the user'
    if passes:
        lines.append(f'{doc.name}: {" -> ".join(map(str, curve))} prose words, '
                     f'{curve[-1] / curve[0] * 100:.1f}% of the peak after {passes} pass{"es" if passes != 1 else ""}.')

    removed = curve[0] - curve[-1]
    parked = prose.count_words(text)[1] - state['peak_hidden']
    if removed > 0 and parked >= prose.PARKED_FLOOR and parked >= removed * prose.PARKED_SHARE:
        lines.append(f'{removed} prose words left the count and {parked} appeared in code blocks, inline code or '
                     'comments. Distillation removes words; it does not move them. Cut them unless they are a real example.')

    if not passed:
        if state.get('fruitless', 0) >= STALL_ATTEMPTS:
            return False, lines + stall(doc, folder, state)
        save_state(folder, root, state)
        lines += [exits(curve[0], state['preset']), phase_instruction(passes + 1, bool(state['reference'])),
                  f'Then run: {run_line(doc)}']
        return False, lines

    if flag == 'reviewed':
        state['reviewed_at'] = count
    save_state(folder, root, state)

    if state['reviewed_at'] != count:
        if state.get('review_asked_at') is None:
            state['review_asked_at'] = count
            save_state(folder, root, state)
        lines += [
            f'Distilled ({reason}). Next: a blind review.',
            'Dispatch a subagent that has not seen your passes. Give it these two files, the question below, '
            'and nothing about why you cut what you cut:',
            f'  peak:    {folder / "peak.md"}',
            f'  current: {doc}',
            '  "What in the peak does a reader of the current doc need, and cannot act correctly without? '
            'Facts, instructions, numbers and constraints, and the reasons, examples or emphasis a rule '
            'depends on. List only those."',
            f'Restore only those, at most {int(RESTORE_ALLOWANCE * 100)}% more words, then run: '
            f'{run_line(doc, "--reviewed")}',
        ]
        return False, lines

    return True, lines + finish(doc, text, state, folder, curve, reason)


def main():
    parser = argparse.ArgumentParser(description='Distill one markdown doc in measured passes.')
    parser.add_argument('doc')
    # The preset may also follow the doc as a plain word, the way the skill's
    # usage line shows it.
    parser.add_argument('preset_word', nargs='?', choices=sorted(prose.PRESETS), metavar='preset')
    parser.add_argument('--preset', choices=sorted(prose.PRESETS))
    group = parser.add_mutually_exclusive_group()
    for name in ('reviewed', 'stop', 'undo', 'agent', 'reset'):
        group.add_argument(f'--{name}', action='store_true')
    args = parser.parse_args()

    doc = Path(args.doc)
    if not doc.is_file():
        print(f'distill: {args.doc} is not a file', file=sys.stderr)
        sys.exit(2)

    flag = next((name for name in ('reviewed', 'stop', 'undo', 'agent', 'reset')
                 if getattr(args, name)), None)
    done, lines = step(doc, flag, args.preset or args.preset_word)
    print('\n'.join(lines))
    stalled = any(line.startswith('STALLED') for line in lines)
    sys.exit(0 if done else 3 if stalled else 1)


if __name__ == '__main__':
    main()
