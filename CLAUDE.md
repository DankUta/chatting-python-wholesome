# chatting-python-wholesome

A Python pipeline (`chatting.py`) that renders a 1080p countdown video from Google
Sheet rankings, using `yt-dlp` for clips and `ffmpeg` for cutting, overlaying and
concatenating.

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
