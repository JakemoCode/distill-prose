# Changelog

All notable changes to distill-prose. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## 0.3.2 - 2026-09-25

### Security

- The prompt log is private. It moved from a shared `distill-prose` temp folder to `distill-prose-<uid>`, with a `700` folder and `600` files, and the plugin refuses a folder that is a link or belongs to another user. On Linux the old folder was readable by every user on the machine. It is removed on the first hook run.

### Fixed

- A corrupt or half-written session file no longer crashes every distillation until it expires. Session files are written atomically, and unreadable ones are skipped.
- A hook that hits an error, such as a stamped doc that isn't UTF-8, exits quietly instead of printing an error on every prompt and edit.

### Added

- The README explains the approval prompt for `distill.py` and why it asks again after updates.
- This changelog.

## 0.3.1 - 2026-09-25

### Added

- A pass that adds a number, command, identifier, URL, path, version or ALL-CAPS word the draft never had is refused. Setting the draft's own commands in code is not invention, and a number only has to match its digits.

### Fixed

- A number or URL at the end of a sentence is recognized as an anchor. It used to be skipped, or kept the period as part of the URL.

### Removed

- Re-reading anchors when a pass raised the peak. With inventions refused, it could only protect an invention or a newly backticked command.

## 0.3.0 - 2026-09-25

### Changed

- The skill runs only when invoked: `/distill-prose:distill <doc> [moderate|relaxed]`. Asking Claude to shorten a doc gets a normal edit.
- The preset can follow the doc as a plain word.

## 0.2.0 - 2026-09-24

### Added

- A distillation ends after 5 attempts in a row that get nowhere, releases the agent, and stamps nothing.
- Dictation is detected from the user's prompts, which replaces the `--dictated` flag.
- A non-default preset needs its name in something the user typed. Accepting a doc as it stands needs a one-time phrase the user types.

### Changed

- The prompt log keeps 10 prompts per session instead of 50, and session files untouched for a day are deleted.

## 0.1.0 - 2026-09-23

### Added

- First release: measured passes (grammar, shape, fluff) judged by docs-distillation-gate's counter, anchor checks, a blind review before `DONE`, stamps, a per-folder sidecar for untracked docs, and hooks that make an agent distill what it adds to a stamped doc.

