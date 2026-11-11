# linkedin-publisher

A self-contained skill folder for an AI assistant (Claude Cowork, Claude Code, or any agent that
can run Python) to **draft, preview, and publish text posts to LinkedIn** through Composio.

- **No installation step.** Every script uses the Python 3.8+ standard library only — no `pip`,
  no virtualenv, no third-party packages.
- **Nothing is published without a preview and an explicit approval.** `--dry-run` never posts.
- **No machine-specific paths.** The agent resolves the skill folder at runtime, so the same zip
  works on any laptop.
- **A local archive of every draft.** `scripts/stage_draft.py` keeps each version in
  `<workspace>/posts/`.

## Contents

```
linkedin-publisher/
├── SKILL.md            # the operating rules the agent follows
├── README.md           # this file
├── .env.example        # configuration template
├── requirements.txt    # states: no dependencies required
├── scripts/
│   ├── post_linkedin.py  # inspect / preview / publish a post
│   ├── stage_draft.py    # archive a draft into <workspace>/posts/
│   └── doctor.py         # read-only setup checker (masks every secret)
└── tests/
    └── test_post_linkedin.py  # offline unittest suite, no network, no credentials
```

## Install it into Claude Cowork

1. Copy the whole `linkedin-publisher` folder into the workspace you give Cowork.
   Keep the folder name — `SKILL.md` and `scripts/` must stay together.
2. Or, to upload it as a skill: zip the folder (`linkedin-publisher.zip`) and add it through the
   Cowork skills / attachments control, then point the assistant at `SKILL.md` inside it.
3. Put the credentials in a `.env` file (see below) and have the agent run the doctor once:

   ```bash
   python3 linkedin-publisher/scripts/doctor.py
   ```

`RESULT: READY` means the workspace is set up. `RESULT: FAILED` names the missing pieces; the
doctor never posts anything and never prints a key.

## Where `.env` goes

The first existing file wins:

1. `--env-file <path>` on the command line
2. the path in the `LINKEDIN_PUBLISHER_ENV_FILE` environment variable
3. `linkedin-publisher/.env` — inside the skill folder (travels with the zip)
4. `<workspace>/.env` — next to the skill folder (easiest for one project)
5. `<parent of workspace>/.env` — handy when several projects share one account

A variable that is already set in the real environment always beats the file's value; the file only
fills in what is missing. `.env` is git-ignored in this repository — do not commit it.

Required keys: `COMPOSIO_API_KEY`, `COMPOSIO_USER_ID`.
Optional: `COMPOSIO_CONNECTED_ACCOUNT_ID`, `LINKEDIN_AUTHOR_URN`, `LINKEDIN_AUTH_CONFIG_ID`
(the last one is only for the one-time LinkedIn connection, which happens outside this bundle).

## Quickstart

```bash
# 1. check the setup (read-only, secrets masked)
python3 scripts/doctor.py

# 2. preview — nothing is published
python3 scripts/post_linkedin.py --dry-run --file /absolute/path/to/workspace/posts/draft.md --json

# 3. publish, only after you approve the exact previewed text
python3 scripts/post_linkedin.py --publish --file /absolute/path/to/workspace/posts/draft.md --json
```

Keep drafts in the workspace instead of typing them on the command line:

```bash
python3 scripts/stage_draft.py --workspace /absolute/path/to/workspace --stdin < my-text.md
python3 scripts/stage_draft.py --workspace /absolute/path/to/workspace --list
```

## Using it directly (no agent involved)

| Command | What it does |
|---|---|
| `post_linkedin.py --inspect` | Prints the Composio post tool's slug, version, and input schema. Read-only. |
| `post_linkedin.py --dry-run --file draft.docx` | Resolves account and author, prints the exact payload. Never publishes. |
| `post_linkedin.py --publish --file draft.md` | Publishes a real, public LinkedIn post. |
| `post_linkedin.py --publish 'Inline text'` | Publishes text typed on the command line. |
| `--json` | Machine-readable output on stdout and nothing else, for an agent to parse. |
| `--extra '{"visibility": "CONNECTIONS"}'` | Extra post fields; unknown keys are rejected. |
| `--max-chars 3000` | Refuses posts longer than the limit (default 3000). |
| `--env-file /path/.env` | Use one specific configuration file. |

Accepted post files: `.txt`, `.md` (read as literal text — Markdown is **not** rendered by
LinkedIn) and `.docx` (paragraphs, table cells, tabs and line breaks in document order).
Exit code is `0` on success, `1` on any setup, network, or API error, which is printed as a single
`ERROR: ...` line on stderr.

## Run the tests

From the folder that contains `linkedin-publisher`:

```bash
python3 -m unittest discover -s linkedin-publisher/tests -t linkedin-publisher/tests -v
```

The suite is fully offline: it stubs the Composio client, works in temporary directories, and needs
no credentials. It also passes when the bundle is used standalone from a zip — the tests that touch
the parent repository skip themselves.

## Security notes

- The Composio API key is only ever sent to `backend.composio.dev` as the `x-api-key` header.
- `doctor.py` reports key length and never the value; `--json` output contains the post text and
  account ids, not credentials.
- Publishing is a public act on a real profile. Keep the preview-and-approval loop in `SKILL.md`
  intact if you edit it.
