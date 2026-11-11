---
name: linkedin-posting
description: Use when drafting, previewing, or publishing a LinkedIn text post through this repository's Composio connection, including drafts retrieved from Google Drive. Repo-bound entry point; see linkedin-publisher/SKILL.md for the full conversational workflow.
---

# LinkedIn posting (repository entry point)

Run the CLI from the repository root with a relative path — never an absolute path copied from
another machine, and never a hardcoded interpreter path (a virtualenv location from someone else's
laptop will not exist here):

```bash
python3 post_linkedin.py --dry-run --file "posts/draft.docx" --json
```

`post_linkedin.py` at the root is a thin wrapper: it loads the canonical implementation from
`linkedin-publisher/scripts/post_linkedin.py`, so the repository CLI and the portable skill bundle
can never drift apart. The bundle needs nothing installed — Python 3.8+ standard library only.
If the workspace has its own virtualenv interpreter (`venv/bin/python`), that works too.

## Configuration

`.env` is discovered in this order (first file found wins, and any variable already set in the real
environment beats the file): `--env-file`, `LINKEDIN_PUBLISHER_ENV_FILE`, the skill root
(`linkedin-publisher/.env`), the current directory, the parent directory. Check it read-only with:

```bash
python3 linkedin-publisher/scripts/doctor.py
```

## Inputs

For a draft in Google Drive, search by filename with
`python3 linkedin-publisher/scripts/drive_draft.py --search "phrase" --json`, show matching titles
and IDs when there is ambiguity, then import the selected file with `--file-id ID --workspace "$PWD"
--json` (or `--url LINK`). The returned local `path` is the staged snapshot to preview and publish.
The Drive command never posts. Google Drive must be connected to the same Composio user as LinkedIn.

Use either inline text or one local file as the post body. Supported files are UTF-8 `.txt` and
`.md`, and `.docx`. The file content becomes the LinkedIn post text; a file is not uploaded as an
attachment, and Markdown is posted as literal text. `--extra` accepts an optional JSON object of
additional Composio post fields; `--max-chars` (default 3000) refuses an over-long post.
Exactly one of `--inspect`, `--dry-run`, `--publish` is required, and `--json` prints a single
machine-readable object and nothing else.

## Approval and execution

1. Draft the post or read the supplied file. Run `--dry-run` to inspect the exact post text and
   arguments that would be sent. A dry run never publishes.
2. Show the final text and any extra fields to the user. Obtain explicit approval of that specific
   post and target account before publishing.
3. If publishing from a file, confirm its content still matches the approved preview. Run the
   matching `--publish` command only after approval, on the same file.
4. Report the command result. A successful Composio response should be checked on the LinkedIn
   profile for visibility.

Do not publish merely because the user asked to set up or test this skill. Do not edit the posting
script during normal skill use; use its CLI arguments.

## Full workflow

`linkedin-publisher/SKILL.md` is the complete, machine-portable version of these rules — conversational
drafting, plain-text formatting for LinkedIn, staging drafts into `posts/`, the mandatory preview
card, and the approval gate. Use it whenever the skill folder is installed in a workspace.
