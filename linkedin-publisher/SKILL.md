---
name: linkedin-publisher
description: Use when drafting, retrieving a Google Drive draft, previewing, or publishing a LinkedIn text post through Composio. Standard-library-only Python scripts; every post is previewed and explicitly approved before it goes live.
---

# LinkedIn publisher

Draft, preview, and publish **text-only** LinkedIn posts through Composio, for a user who does not
work with terminals. The scripts need no `pip install`. The publish step is real and public: never
run it without approval of the exact text you just previewed.

## 1. When to use this skill

Use it for: drafting a LinkedIn post, rewriting or polishing a post the user already wrote,
previewing a post before it goes out, publishing a `.txt` / `.md` / `.docx` file as a LinkedIn post,
or checking that the Composio connection is configured.

Do not use it for: LinkedIn image or video posts, article shares, reposts, comments, messaging,
analytics, or any other network. This skill posts plain text only.

## 2. One-time setup (once per machine, then forget it)

1. Copy the `linkedin-publisher` folder into the user's workspace.
2. Create a `.env` file containing the Composio credentials. It is read from either of two places
   (checked in this order): the **workspace root**, or **inside this skill folder**. Copy
   `.env.example` to `.env` and fill in:

   ```dotenv
   COMPOSIO_API_KEY=...            # required - Composio dashboard, Settings > API Keys
   COMPOSIO_USER_ID=...            # required - the Composio end-user this LinkedIn account is linked to
   LINKEDIN_AUTH_CONFIG_ID=...     # optional - only for the one-time account connection
   COMPOSIO_CONNECTED_ACCOUNT_ID=  # optional - pin one account when several are ACTIVE
   LINKEDIN_AUTHOR_URN=            # optional - urn:li:person:... if auto-lookup fails
   GOOGLEDRIVE_CONNECTED_ACCOUNT_ID=  # optional - pin one Google Drive account
   ```

3. Verify with the read-only checker. It prints what it found, masks every secret, and never posts:

   ```bash
   python3 <skill_root>/scripts/doctor.py
   ```

   `RESULT: READY` means setup is done. `RESULT: FAILED` lists exactly what is missing — fix that,
   rerun doctor, and do not attempt a publish in the meantime.

4. Connect the LinkedIn account to Composio once, from a machine that has the optional `composio`
   SDK (see the repo README). This skill itself needs nothing installed.

5. For Drive drafts, connect Google Drive to the **same** Composio project and user ID, with read
   access to the client's draft files. The Composio API key needs proxy execute permission. If there
   are multiple ACTIVE Drive connections, pin the correct one in `.env`.

Never ask the user to paste their API key into chat, never write it into a file you generate, and
never echo it in a command or a log.

## 3. How to run the scripts — path rules

- **Never hardcode an absolute machine path** — no home-directory path copied from another laptop,
  no interpreter path baked into a command, no path recalled from an earlier session.
- Work out `<skill_root>` at runtime: it is the folder that contains this `SKILL.md`, which also
  contains `scripts/`. Every command uses that folder as an anchor:

  ```bash
  python3 <skill_root>/scripts/post_linkedin.py --dry-run --file <draft path> --json
  python3 <skill_root>/scripts/stage_draft.py --workspace <workspace> --stdin
  python3 <skill_root>/scripts/doctor.py
  ```

- Prefer a workspace virtualenv's interpreter if one exists (`<workspace>/venv/bin/python`),
  otherwise plain `python3`. The bundle is standard library only, so either works.
- Always pass **absolute** paths for `--file` and `--workspace`; do not rely on the current
  directory.
- If `scripts/post_linkedin.py` is not where you expect, stop and look for the skill folder rather
  than guessing a path. Do not copy the script somewhere else to make a path work.

## 4. The mandatory workflow — in order, never skip a step

### a. Draft conversationally

Ask at most 2-3 clarifying questions (topic, audience, tone) and only when the request is genuinely
ambiguous. If the user gave you the substance already, draft immediately — do not interrogate them.

### b. Format for LinkedIn plain text

LinkedIn renders literal characters, so **never emit Markdown**. In the post body:

- no `**bold**`, no `#` headings, no `*` or `_` emphasis, no backticks, no `>` block quotes
- no `[text](url)` links — write the URL out in full, or drop it
- no tables, no horizontal rules, no Markdown checkboxes
- separate paragraphs with a blank line
- use `•` for bullets and `—` for an aside
- put 3-5 hashtags on one line at the very end

Keep it human: short paragraphs, one clear takeaway, one call to action, no corporate filler, no
hashtags inside the body. Target 600-1300 characters. LinkedIn's hard limit is 3000 and the script
enforces it (`--max-chars`, default 3000).

### c. Stage the draft

If the source is on Google Drive, first locate it. Use the user's exact link when available; otherwise
search by filename and show the matching titles/IDs if more than one is plausible. Do not guess which
document they meant. Import the selected file into the workspace's `posts/` directory:

```bash
python3 <skill_root>/scripts/drive_draft.py --search "filename phrase" --json
python3 <skill_root>/scripts/drive_draft.py --file-id <selected ID> --workspace <workspace> --json
# Or use --url <Google Docs/Drive link> instead of --file-id.
```

The importer accepts Google Docs and stored `.txt`, `.md`, or `.docx` files. It returns the Drive
source metadata and local staged `path`; it never publishes. Review the imported text and format it
for LinkedIn plain text. If changes are needed, save a new staged version with `stage_draft.py`. Show
the user which Drive document was used and retain the staged file for the preview and publish steps.

Archive every iteration so the user keeps a local copy:

```bash
python3 <skill_root>/scripts/stage_draft.py --workspace <workspace> --stdin   # body piped in
```

It writes `<workspace>/posts/YYYY-MM-DD-<slug>.md` and prints only that absolute path. It never
overwrites: the second version of the same headline becomes `...-2.md`. Tell the user the path.
Use `--list` to show what is already staged.

### d. Preview (mandatory, every time)

Before anything is published, always run the dry run on the staged file:

```bash
python3 <skill_root>/scripts/post_linkedin.py --dry-run --file <staged path> --json
```

`--json` makes the script print a single machine-readable object
(`mode`, `env_file`, `account_id`, `user_id`, `author`, `toolkit_version`, `visibility`, `text`,
`char_count`, `hashtags`, `arguments`, `published`, `log_id`, `data`) and nothing else.
`--dry-run` never publishes. Then show the user a preview card:

```
Preview — not posted yet
<Post text exactly as it will be published, in a fenced block>
Characters: <char_count>
Hashtags: <hashtags joined with a space>
Posting to: <account_id> as <author>
Visibility: <visibility>  |  Toolkit version: <toolkit_version>
Will run: python3 <skill_root>/scripts/post_linkedin.py --publish --file <staged path> --json
```

The text in the card must be byte-for-byte what the dry run reported, not a re-typed or
re-formatted version.

### e. Approval gate

Publish only after the user explicitly approves **that** preview: "publish it", "post it",
"looks good, post it", "go ahead", "approved". Anything else is not approval — not silence, not
"great idea!", not "nice", not enthusiasm about an earlier draft.

- If you change the draft after approval (wording, hashtags, length, the file itself), the approval
  is void: re-stage, re-run the dry run, and ask again about the new text.
- If the preview shows a different account, author, or visibility than expected, stop and confirm
  with the user before publishing.
- Never publish "to test it", "to see if it works", or while the user only asked you to set up or
  troubleshoot the skill. A test post is a real post on their profile.

### f. Publish

Run exactly the same command with `--publish`, on the **same file** that was approved:

```bash
python3 <skill_root>/scripts/post_linkedin.py --publish --file <staged path> --json
```

Do not switch to inline text, a different file, or a different `--extra` between the preview and the
publish.

### g. Report

From the JSON, show the post/response id (`data`), the `log_id`, and `published: true`. Then remind
the user, in plain words, to open their LinkedIn profile and confirm the post is visible. A
successful Composio response is not proof the post rendered the way they wanted.

## 5. Hard rules

- Never publish without explicit approval of the exact previewed text.
- Never publish a file whose content changed since approval.
- Never publish inline text when a file was approved (or vice versa).
- Never use Markdown formatting in the post body.
- Never publish while the user only asked to install, set up, test, or debug the skill.
- Never edit the posting scripts during normal use — use CLI flags (`--extra`, `--max-chars`,
  `--env-file`) instead.
- Never print, echo, log, or store the Composio API key.
- Never claim a post is live without the publish result and a user confirmation on the profile.

## 6. Extra options

- `--extra '{"visibility": "CONNECTIONS"}'` — forward extra post fields. Unknown keys are rejected;
  run `--inspect` to see the current field names.
- `--env-file <absolute path>` — use a specific `.env` when several projects live in one workspace.
- `--max-chars <N>` — override the length guard (default 3000).
- `--inspect` — read-only: prints the post tool's slug, version, and input schema.

## 7. Troubleshooting

Every failure prints one line starting with `ERROR:` and exits 1. Quote that line to the user and
act on it; do not retry the same command hoping for a different result.

| Symptom | What to do |
|---|---|
| `COMPOSIO_API_KEY is missing from .env` / no env file found | Run `doctor.py`, then create `.env` in the workspace root or the skill folder. |
| `Env file not found: ...` | The `--env-file` path is wrong — pass the real absolute path. |
| `Composio HTTP 401` / `403` | Wrong key or key from another Composio project. Re-copy it from that dashboard; never regenerate blindly. |
| `Network error contacting Composio` | No internet or the endpoint is blocked. Check connectivity, then retry once. |
| `No ACTIVE LinkedIn connection matches COMPOSIO_USER_ID` | The account is not connected (or is connected under a different `COMPOSIO_USER_ID`). Redo the one-time LinkedIn connection, then re-run the dry run. |
| `Multiple ACTIVE LinkedIn accounts belong to this user` | Set `COMPOSIO_CONNECTED_ACCOUNT_ID` to one of the listed ids and ask the user which profile they mean. |
| `Could not retrieve LinkedIn member ID` / no author URN | Set `LINKEDIN_AUTHOR_URN=urn:li:person:<member-id>` in `.env`. |
| `Post is N characters, M over the 3000-character limit` | Shorten the draft by at least M characters, re-stage, re-preview. |
| `Unsupported post file type` | Only `.txt`, `.md`, and `.docx` are readable — convert the file to one of those. |
| `Cannot read post file ... contains no text` | The file is empty or unreadable. Stage the draft again. |
| `Unknown extra argument(s)` | Drop the key or fix its spelling; `--inspect` lists the valid ones. |

If a retry of the same approved command fails twice with the same error, stop and report it to the
user with the exact message instead of trying variations.
