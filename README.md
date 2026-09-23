# distill-prose

## What it does

Agents love prose. Prose rots brains. distill-prose makes an agent cut a markdown doc down in measured passes, and it checks the cut with numbers instead of taking the agent's word for it.

Point it at one doc. A script counts the prose after every pass and prints the agent's next instruction. The doc is done at half its longest draft, or when cutting stops paying off: 3+ passes, the last 2 each under 5%, ending at 65% or less. Before it says done, a second agent that never saw the cuts compares the original with the result and lists anything that went missing.

Then it stamps the doc. When an agent later adds to a stamped doc, like a new rule in AGENTS.md, hooks catch it, and the agent has to distill its addition before it can end its turn. Text you write yourself is never billed.

## How to use it

### Install

```
/plugin marketplace add JakemoCode/distill-prose
/plugin install distill-prose@distill-prose
```

It needs `python3` and nothing else. In Cowork, the plugin installs from the Customize tab. It hasn't been tested there yet.

### Distill a doc

Ask Claude: "distill docs/setup.md". The skill runs the script and does what it prints. That means a grammar pass in ASD-STE100 Simplified Technical English, then a pass that turns the content into a procedure, a table or a list where it fits, then passes that cut fluff until the numbers say stop.

The script refuses a pass that breaks the method, and says why:

- a grammar pass that cut more than 10%
- a shape pass that cut more than 30%
- a number, command, identifier, URL, path or ALL-CAPS word that disappeared
- a change to text that was already distilled

### Presets

| Preset | Done at | Or converged at |
| --- | --- | --- |
| aggressive (default) | 50% | 65% |
| moderate | 60% | 75% |
| relaxed | 70% | 85% |

You pick the preset. For CLAUDE.md, AGENTS.md or a skill, Claude will suggest moderate and ask. The preset is saved in the doc's stamp.

### Things only you can say

- "Stop here." Claude ends the distillation early, and the stamp says `stopped`.
- "Those were my words." Text Claude wrote for you word for word isn't billed.

### What it writes

- A stamp on the first line after any frontmatter: `<!-- distill-prose a1b2c3 moderate 539->310 -->`.
- For a git-tracked doc, nothing else. Commit when it's done, and that commit is the reference point next time.
- For an untracked doc, a `.distill.json` in the same folder, holding a hash and word count per paragraph. It stores no text.
- A `.distill/` scratch folder while a distillation runs. It ignores itself in git.

## Why I built it

Ask a model to be concise and you get a doc that sounds concise. I built [docs-distillation-gate](https://github.com/JakemoCode/docs-distillation-gate) to measure that in CI. distill-prose is the same measurement for any file in any folder, with no CI and no git required. It also covers the docs that keep growing after they've been cut, which are the ones agents write into most: AGENTS.md, CLAUDE.md and runbooks.

## How it works

The counter is a port of the gate's. Only prose counts. Code blocks, inline code, HTML comments and markdown syntax don't. `fixtures/counting` holds cases the gate itself produced, and both counters must agree on them.

A stamped doc is billed only for new text. The doc is split into blocks (paragraphs, list items, table rows, headings) and compared with the version at the stamp. A new block is billed in full, and an edited block only for its growth, so fixing a typo costs nothing.

Anchors are the exact-match facts in the peak draft: code, identifiers, numbers, URLs, paths, versions and all-caps emphasis. Every pass is checked against them. The blind review at the end catches what exact matching can't, including lost reasons, examples and emphasis.

The hooks diff a stamped doc's blocks around every Edit or Write, which records exactly what the agent added. The Stop hook blocks the end of a turn while the agent owes 50 or more words. It blocks once, so a session that can't distill isn't trapped.

In a repo that runs docs-distillation-gate, the skill hands the doc to the gate.

[DESIGN.md](DESIGN.md) has every decision and the reason for it.

### What it can't do

- It can't tell a good cut from a bad one. It proves that editing happened and that exact facts survived. The blind review is the only check on meaning.
- It only sees edits made through the Edit and Write tools. An agent that rewrites a doc with `sed` goes unbilled.
- The thresholds came from a small sample. Treat early results as calibration.

MIT licensed. Python standard library, no dependencies.
