# chatting-python-wholesome

The admin side of "Chatting", a friends' song contest: Google Form submissions → an
anonymous rating sheet → a master spreadsheet of everyone's ratings → a 1080p countdown
video. A Python package run as `python -m chatting <command>`; `yt-dlp` fetches the
clips and `ffmpeg` renders them. README.md is the user guide.

## Layout

| Path | What |
| --- | --- |
| `chatting/cli.py` | Commands: `init`, `check`, `sheet`, `compile`, `preview`, `render` |
| `chatting/config.py`, `models.py`, `names.py`, `log.py` | Settings (`chatting.toml`), shared dataclasses, name matching across spellings, console output |
| `chatting/sources.py`, `submissions.py`, `timestamps.py`, `links.py` | Reading sheets (local or Google links), the form responses, clip start times |
| `chatting/ratings.py`, `master.py` | The rating sheet (write + read back), averages/ranks and the master workbook |
| `chatting/text.py`, `avatars.py`, `overlay.py` | On-screen graphics: font/emoji fallback, profile pictures, per-song overlays |
| `chatting/clips.py`, `render.py` | yt-dlp downloads (cached, rate-limited) and ffmpeg segments + concat |
| `examples/demo/` | A made-up edition with filled-in rating sheets, for trying the commands |

Contest rules baked in: a voter's rating of their own song never counts; tied averages
share a rank; every comment is shown (paginated over the clip when they don't fit).

## Checks

- Tests: `python -m pytest` (~2 min; the ffmpeg ones are marked `slow`, skip them with
  `-m "not slow"`). No test touches the network.
- Keep Python 3.9 compatible (`from __future__ import annotations`, no `match`).

## Agents and routing

Four subagents live in `.claude/agents/`. Each one's `description` is what Claude
matches on, so routing happens automatically; this section is the explicit version
of the same flow.

| Agent | Model | When to use it |
| --- | --- | --- |
| `scoper` | haiku | Start of a non-trivial task in unfamiliar code: find the relevant files, tests, entry points and conventions before planning. Read-only. Skip when fewer than 3 unread files are expected. |
| `implementer` | sonnet | The solution is already decided and the change is well defined — multi-file edits, or anything needing more than one edit-and-test cycle. Writes code and tests and runs the project's checks. |
| `reviewer` | opus | Independent second opinion: when the user asks for one, or for risky changes (security, auth, concurrency, data migrations, broad public API changes). Read-only. |
| `shipper` | haiku | Git and GitHub steps only — commit, push, open a PR — after the change is reviewed and verified and the user asked to ship. Never edits files. |

Typical order: **scoper → (main session plans) → implementer → reviewer → shipper.**
Each step is optional; skip the ones the task does not need.

Routing rules:

- Architecture, scoping decisions and root-cause analysis stay in the main session —
  `implementer` builds what has already been decided, it does not decide.
- Small, obvious single-file edits: do them directly, do not spawn an agent.
- `scoper` and `reviewer` never change anything; `shipper` never touches project files.
- Hand off explicitly. An `implementer` handoff needs acceptance criteria, the relevant
  files, decisions already made, edge cases, and the validation commands to run. A
  `shipper` handoff needs the exact file list, branch name, commit message, and PR
  title and body.
- `shipper` runs git/GitHub commands only; nobody else commits, pushes or otherwise
  changes history or remote state.

## Conventions

- Commits and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/):
  `type(scope): summary`, e.g. `feat(render): ...`, `fix(download): ...`.
- Micro commits: one logical change per commit (a module, or a fix with its test), not
  one big commit at the end.
