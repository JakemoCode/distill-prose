# distill-prose

A Claude Code plugin that cuts markdown docs down in measured passes and keeps them cut.

Agents love prose. Prose rots brains. Ask a model to be concise and you get a doc that sounds concise. distill-prose measures the doc instead. A script counts the prose after every pass, the doc isn't done until the numbers say so, and a second agent checks that nothing a reader needs was lost.

It's the per-doc companion to [docs-distillation-gate](https://github.com/JakemoCode/docs-distillation-gate), which enforces the same measurement in CI. distill-prose needs no CI and no git.

## Install

Requires Claude Code and `python3`. It uses the standard library only.

```
/plugin marketplace add JakemoCode/distill-prose
/plugin install distill-prose@distill-prose
```

Start a new session, or run `/reload-plugins`. To update later, run `/plugin marketplace update distill-prose` and then `/plugin update distill-prose@distill-prose`, and restart.

Cowork installs Claude Code plugins from its Customize tab, but this one hasn't been tested there yet.

## What it does

- **Distills one doc, only when you ask.** Run `/distill-prose:distill docs/setup.md`. Claude never starts it on its own, so asking to "shorten" something gets a normal edit. Claude makes a grammar pass in ASD-STE100 Simplified Technical English, then a pass that turns the doc into a procedure, table or list where it fits, then passes that cut fluff. It's done when the doc is at half its longest draft, or when cutting stops paying off.
- **Checks that the facts survived.** Every number, command, identifier, URL, path and ALL-CAPS word from the draft must still be there after each pass. Before it finishes, a subagent that never saw the cuts compares the draft with the result and lists what a reader would miss.
- **Keeps the doc cut.** A distilled doc gets a stamp comment on its first line. When an agent later adds to a stamped doc, it has to distill its addition before it can end its turn. Text you write yourself, or dictate word for word, is never billed.
- **Stops instead of grinding.** After 5 attempts in a row that get nowhere, the run ends and Claude shows you the curve. Nothing is stamped.

## How it works

**Counting.** Only prose counts. Code blocks, inline code, HTML comments and markdown syntax don't. The counter is a port of docs-distillation-gate's, and both must pass the cases in `fixtures/counting`.

**The curve.** The script records the prose count after every pass. A doc passes at its preset's target share of its longest draft. It also passes if it converges: 3+ passes, the last 2 each cutting under 5%, ending at or below the preset's ceiling. A pass that breaks the method is refused. That covers a grammar pass that cuts, a shape pass that deletes, a dropped anchor, or an edit to text that was already distilled.

**Living docs.** A stamped doc is billed only for new text. The script splits the doc into paragraphs, list items, table rows and headings, and compares them with the version at the stamp. For a git-tracked doc, that's the commit that carries the stamp. For an untracked doc, it's a `.distill.json` beside the doc, holding a hash and word count per block and no text.

**Hooks.** The hooks are the only automatic part, and they only act on docs someone chose to distill. Edit and Write hooks record exactly what an agent writes into a stamped doc. A Stop hook blocks the end of a turn while the agent owes 50 or more words, and it only blocks once. A prompt hook keeps your last 10 prompts per session in your system temp folder, and deletes a session's file once it has sat untouched for a day. The plugin reads those prompts for three things only: text you dictated, a preset you named, and the `accept` phrase.

**Your decisions stay yours.** The agent can't choose a gentler preset or accept a doc as it stands on its own. The script checks what you typed.

In a repo that runs docs-distillation-gate, the skill hands the doc to the gate. [DESIGN.md](DESIGN.md) records every decision and the reason for it.

## Configuration

There's no config file. You control these:

| Setting | How | Default |
| --- | --- | --- |
| Preset | Add it after the doc: `/distill-prose:distill AGENTS.md moderate` | aggressive |
| Accept a doc as it stands | Reply with the `accept` phrase Claude shows you, such as `accept 3f9a2c` | off |
| Hooks and skill | `/plugin disable distill-prose@distill-prose` | on |

| Preset | Done at | Or converged at |
| --- | --- | --- |
| aggressive | 50% | 65% |
| moderate | 60% | 75% |
| relaxed | 70% | 85% |

The preset is saved in the doc's stamp, so re-distilling a doc reuses it. The thresholds (the 50-word floor, 5 fruitless attempts, the 10% grammar limit) are constants in `skills/distill/scripts/`, for anyone forking.

What it writes:

- a stamp on the first line after any frontmatter: `<!-- distill-prose a1b2c3 moderate 539->310 -->`
- `.distill.json` beside an untracked doc
- a `.distill/` scratch folder during a run, which ignores itself in git and is removed at the end
- session files in `$TMPDIR/distill-prose/`, which expire after a day

## Limits

- It proves that editing happened and that exact facts survived. Only the blind review judges meaning.
- It only sees edits made through the Edit and Write tools. An agent that rewrites a doc with `sed` goes unbilled.
- The thresholds came from a small sample. Treat early results as calibration.

## License

MIT
