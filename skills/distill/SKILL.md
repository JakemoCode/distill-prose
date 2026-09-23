---
name: distill
description: Distill a markdown doc in measured passes until its prose halves or stops falling. Use when asked to distill or shorten a doc, before the first edit, or when a Stop hook says you owe a distillation.
---

# Distill

Script paths are relative to this skill's directory. In Claude Code, `${CLAUDE_SKILL_DIR}` is that directory.

```sh
python3 "${CLAUDE_SKILL_DIR:-.}/scripts/distill.py" <doc>
```

**The script's output is your next instruction.** Run it before your first edit and after every pass, and do exactly what it prints. You are finished only when it prints `DONE` and exits 0. When a Stop hook says you owe a distillation, run the command the hook gives. When the script prints `STALLED`, the text resists cutting: make no more passes, tell the user the curve and the options it prints, and end your turn.

When `python3` is missing or the command is refused, stop and tell the user. distill-prose measures every pass, and an unmeasured distillation is what it exists to prevent.

## What a pass keeps

Facts, instructions, numbers, constraints, reasons for rules, examples, and deliberate emphasis. The last three read like fluff and carry weight: a reason is how a reader applies a rule to a case the rule does not name. When a cut would remove one a reader needs, name it and ask the user.

## The blind review

When the script asks for one, dispatch a subagent with exactly the two files and the question it prints. Keep your reasoning out of the prompt. A reviewer that knows why you cut something agrees with you.

## Choices that belong to the user

- **Preset.** `--preset aggressive|moderate|relaxed` sets how far the doc falls: 50% of its peak or converged at 65%, 60% or 75%, 70% or 85%. Aggressive is the default. For an instruction file such as CLAUDE.md, AGENTS.md or a skill, suggest moderate and ask. Pass `--preset` only with the user's answer.
- **Dictated text.** Run `--dictated` only when the user supplied the words themselves.
