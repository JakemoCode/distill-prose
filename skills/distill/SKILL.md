---
name: distill
description: Distill a markdown doc in measured passes until its prose halves or stops falling. Usage /distill-prose:distill <doc> [moderate|relaxed]
disable-model-invocation: true
---

# Distill

The script lives in this skill's base directory, the path you were given when the skill loaded:

```sh
python3 "<base directory>/scripts/distill.py" <doc>
```

**The script's output is your next instruction.** Run it before your first edit and after every pass, and do exactly what it prints. You are finished only when it prints `DONE` and exits 0. When the script prints `STALLED`, the session is over and you owe nothing more on the doc: tell the user the curve and end your turn. Some choices need the user's own words. The script says what it needs, and checks what the user typed.

When `python3` is missing or the command is refused, stop and tell the user. distill-prose measures every pass, and an unmeasured distillation is what it exists to prevent.

## What a pass keeps

Facts, instructions, numbers, constraints, reasons for rules, examples, and deliberate emphasis. The last three read like fluff and carry weight: a reason is how a reader applies a rule to a case the rule does not name. When a cut would remove one a reader needs, name it and ask the user.

## The blind review

When the script asks for one, dispatch a subagent with exactly the two files and the question it prints. Keep your reasoning out of the prompt. A reviewer that knows why you cut something agrees with you.

## Choices that belong to the user

- **Preset.** `--preset aggressive|moderate|relaxed` sets how far the doc falls: 50% of its peak or converged at 65%, 60% or 75%, 70% or 85%. Aggressive is the default. For an instruction file such as CLAUDE.md, AGENTS.md or a skill, suggest moderate and ask. The script accepts a preset only once the user has typed its name.
