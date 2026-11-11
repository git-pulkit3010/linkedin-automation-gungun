# LinkedIn Automation (via Composio)

A small Python toolkit for drafting, previewing, and publishing **text posts to LinkedIn** through the
[Composio](https://composio.dev) platform (Composio v3.1 REST API).

Post text can be supplied inline or read from a local `.txt`, `.md`, or `.docx` file. The script
auto-discovers the connected LinkedIn account, resolves your LinkedIn member ID (author URN), and
builds the exact post payload before anything is sent — with a strict `--dry-run` mode that never publishes.

Everything in the `linkedin-publisher/` skill bundle is **Python 3.8+ standard library only**: no
`pip install`, no virtualenv. The root `post_linkedin.py` is a thin wrapper that loads that bundle,
so the repository CLI and the portable bundle are the same code. Only the optional one-time
connection helper (`conn_linkedin_composio.py`) needs third-party packages. Google Drive is read
with the host's native Drive connector, so no Drive connection helper or key exists.

## Project layout

| File | Purpose |
|---|---|
| `post_linkedin.py` | Root CLI wrapper — loads `linkedin-publisher/scripts/post_linkedin.py` |
| `linkedin-publisher/` | Portable, self-contained skill bundle (standard library only) |
| `linkedin-publisher/SKILL.md` | Conversational rules for the agent: draft → stage → preview → approve → publish |
| `linkedin-publisher/scripts/post_linkedin.py` | Canonical CLI: inspect, dry-run, or publish a LinkedIn post |
| `linkedin-publisher/scripts/stage_draft.py` | Archives each draft into `<workspace>/posts/` |
| `linkedin-publisher/scripts/drive_draft.py` | Archives a draft fetched by the host's native Google Drive connector |
| `linkedin-publisher/scripts/doctor.py` | Read-only setup checker (reports keys masked, never posts) |
| `linkedin-publisher/tests/test_post_linkedin.py` | Offline unit tests for the bundle (no network, no credentials) |
| `linkedin-publisher/tests/test_drive_draft.py` | Offline unit tests for the Drive staging path (no network, no credentials) |
| `conn_linkedin_composio.py` | One-time setup: prints the URL to connect your LinkedIn account to Composio |
| `test_composio_conn.py` | Read-only end-to-end checks: API key, tool catalog, connected account, profile endpoint |
| `test_post_file.py` | Offline unit tests (file parsing + CLI behavior, no network) |
| `SKILL.md` | Repo-bound skill entry point (relative paths; points at the bundle) |
| `posts/` | Directory for draft post files (`.txt`, `.md`, `.docx`) |
| `.env` | Local secrets (not committed) |

---

## 1. Prerequisites

- **Python 3.8+** for the `linkedin-publisher` bundle and the posting CLI (developed and tested on
  Python 3.12). No `pip`, no virtualenv, no third-party packages.
- **pip** — only if you want to run the optional one-time connection helper
  (`conn_linkedin_composio.py`), which uses the `composio` SDK.
- A **Composio account** — sign up at [app.composio.dev](https://app.composio.dev)
- A **LinkedIn account** you want to post as

## 2. Required API keys / credentials

Everything is configured in a single `.env` file. `post_linkedin.py` looks for it in this order and
uses the first file that exists (and a variable already set in the real environment always wins over
the file's value):

1. the path given to `--env-file`
2. the path in the `LINKEDIN_PUBLISHER_ENV_FILE` environment variable
3. `linkedin-publisher/.env` (the skill root — travels with the bundle)
4. `.env` in the current directory
5. `.env` in the parent directory

`conn_linkedin_composio.py` calls `load_dotenv()` itself, so keep the file in the project root as
well when you do the one-time connection. Run `python3 linkedin-publisher/scripts/doctor.py` to see
which file was picked up and which keys are present (values are masked).

```dotenv
# --- Required (all scripts) ---
COMPOSIO_API_KEY=...              # Composio API key
COMPOSIO_USER_ID=...              # The Composio end-user ID the LinkedIn account is linked to

# --- Required only for the matching one-time connection helper ---
LINKEDIN_AUTH_CONFIG_ID=...       # Auth config (integration) ID for the LinkedIn toolkit

# --- Optional ---
# COMPOSIO_CONNECTED_ACCOUNT_ID=...   # Pin a specific account when several ACTIVE LinkedIn accounts exist
# LINKEDIN_AUTHOR_URN=urn:li:person:xxxx  # Override the author; otherwise auto-resolved via profile lookup
```

### How to obtain these values

1. **`COMPOSIO_API_KEY`** — Log in to the [Composio dashboard](https://app.composio.dev), go to
   *Settings → API Keys* (or the "Get API Key" section), and copy your project's API key.
2. **`COMPOSIO_USER_ID`** — Any string that identifies the end user inside your Composio project
   (e.g. your email or a username). The LinkedIn connected account must be linked to this same
   `user_id`, and all post execution is performed for this user.
3. **`LINKEDIN_AUTH_CONFIG_ID`** — In the Composio dashboard:
   - Go to *Auth Configs* (Integrations) → **LinkedIn**.
   - Create an auth config using **OAuth2**. Composio's LinkedIn integration uses your own LinkedIn
     app: create one at [developer.linkedin.com](https://www.linkedin.com/developers/apps), request the
     *Sign In with LinkedIn using OpenID Connect* and *Share on LinkedIn* products, then paste the
     app's **Client ID** and **Client Secret** into the Composio auth config.
   - Copy the resulting auth config ID (looks like `ac_xxxxxxxx`) into `.env`.

## 3. Install dependencies

**Posting needs nothing.** The `linkedin-publisher` bundle and the root `post_linkedin.py` wrapper
run on the Python standard library: `urllib` for the Composio v3.1 REST calls, a built-in `.env`
reader, `zipfile` + `xml.etree` for `.docx`. Skip this section unless you need the one-time
connection helper.

Only the one-time connection helpers need third-party packages (they use the `composio` SDK), so
install them in a virtualenv just for that step:

```bash
cd linkedin-automation-gungun

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
python -m pip install composio python-dotenv
```

Reference version this repo was built with: `composio==0.30.0` on Python 3.12. `requests` and
`python-dotenv` are no longer used by the posting CLI or `test_composio_conn.py` — both go through
the standard-library client in the bundle.

## 4. Connect your LinkedIn account (one-time)

```bash
python conn_linkedin_composio.py
```

This prints a **redirect URL**. Open it in a browser, log in with the LinkedIn account you want to
post from, and authorize the app. The connected account is then created in Composio under your
`COMPOSIO_USER_ID`.

## 5. Verify the setup (read-only, publishes nothing)

```bash
python3 test_composio_conn.py
```

Expected output ends with `READ-ONLY CHECKS PASSED`. It reads configuration through the same `.env`
discovery as the CLI, then verifies, in order:

1. The `COMPOSIO_API_KEY` is accepted.
2. The LinkedIn tool catalog (v3.1 latest) contains the posting and profile tools.
3. There is exactly one **ACTIVE** LinkedIn connected account for `COMPOSIO_USER_ID`.
4. LinkedIn's profile endpoint works and derives your author URN
   (`urn:li:person:...`) — needed to post. If it can't derive it, set
   `LINKEDIN_AUTHOR_URN=urn:li:person:<your-member-id>` in `.env`.

---

## 6. Posting: `post_linkedin.py`

### Command-line arguments

| Argument | Meaning |
|---|---|
| `--inspect` | Read-only. Prints the LinkedIn post tool's slug, version, and full input schema. |
| `--dry-run [TEXT]` | Read-only. Resolves the account + author and prints the exact payload that *would* be sent. Never publishes. |
| `--publish [TEXT]` | Publishes a **real** LinkedIn post. |
| `--file PATH` | Read the post body from a `.txt`, `.md`, or `.docx` file (UTF-8). |
| `--extra '{"key": "value"}'` | Optional JSON object of extra post fields forwarded to the tool (e.g. visibility). Unknown keys are rejected. |
| `--env-file PATH` | Use this `.env` instead of discovery. Fails immediately if the file does not exist. |
| `--json` | Prints one machine-readable JSON object on stdout and **nothing else**, for an agent to parse. |
| `--max-chars N` | Refuse posts longer than N characters (default `3000`, LinkedIn's limit). |

Notes:

- Exactly one of `--inspect` / `--dry-run` / `--publish` is required.
- Supply the post text **either** inline **or** via `--file`, never both.
- File contents become the literal post text (a file is not uploaded as an attachment; Markdown is
  posted as plain literal text).
- `.docx` support extracts paragraphs, table cells, tabs, and line breaks in document order.
- By default posts are made **PUBLIC** (the script sets `visibility: PUBLIC` when the tool schema
  supports it). Override via `--extra` if needed.

### Examples

```bash
# Inspect the current LinkedIn tool schema (read-only)
python post_linkedin.py --inspect

# Preview a post from inline text (read-only)
python post_linkedin.py --dry-run 'Hello LinkedIn!'

# Preview a post loaded from a file (read-only)
python post_linkedin.py --dry-run --file posts/draft.md
python post_linkedin.py --dry-run --file /absolute/path/to/draft.docx

# Preview with extra fields
python post_linkedin.py --dry-run 'Hello!' --extra '{"visibility": "CONNECTIONS"}'

# Publish for real
python post_linkedin.py --publish 'Hello LinkedIn!'
python post_linkedin.py --publish --file posts/draft.md

# All options together
python post_linkedin.py --publish --file posts/draft.docx --extra '{"visibility": "PUBLIC"}'
```

A successful publish prints the env file that was used, the account, author URN, toolkit version, the
post arguments, and the Composio execution response (`data` + `log_id`). With `--json` the same
information is one object: `mode`, `env_file`, `account_id`, `user_id`, `author`,
`toolkit_version`, `visibility`, `text`, `char_count`, `hashtags`, `arguments`, `published`,
`log_id`, `data`. Always confirm the post is visible on the LinkedIn profile.

> **Exit codes:** `0` on success, `1` on any setup/network/API error (message goes to stderr).

### Recommended workflow

For a client's Google Drive draft, use the host's **native Google Drive connector** (the Cowork
Drive plugin, or whatever Drive/Google Docs tool the host exposes) — Drive never goes through
Composio. Find the document the user means (their exact link first, otherwise a filename search),
read it (a Google Doc is exported as plain text; stored `.txt`, `.md`, and `.docx` files download as
they are), save it to a local file, then archive it into the local archive:

```bash
python3 linkedin-publisher/scripts/drive_draft.py --file ./drive-export.txt \
    --name "Campaign draft" --id FILE_ID --link "https://docs.google.com/document/d/FILE_ID/edit" \
    --workspace "$PWD" --json
# Or pipe the export: --stdin instead of --file
```

The stager reads Google Doc exports and stored `.txt`, `.md`, `.docx` files; it needs no credentials,
contacts no network, never publishes, and never edits anything in Drive. Use the returned `path` for
the existing dry-run, approval, and publish steps below. If multiple documents match, inspect their
names and modified dates with the user before selecting one.

1. Stage the draft: `python3 linkedin-publisher/scripts/stage_draft.py --workspace "$PWD" --stdin`
   writes `posts/YYYY-MM-DD-<slug>.md` and prints that path.
2. Run the matching `--dry-run --file <that path> --json` command and review the exact post text and payload.
3. Only after approving that exact preview, run the matching `--publish --file <that path> --json`
   command — the same file, unchanged.

## 7. The `linkedin-publisher` skill bundle

`linkedin-publisher/` is the portable, self-contained half of this repo — the folder you hand to
Claude Cowork (or any agent) so a non-technical user can draft, preview, and publish without opening
a terminal herself.

| Path | What it does |
|---|---|
| `SKILL.md` | The operating rules the agent follows: when to use, path rules, draft → format → stage → preview → approve → publish → report, hard rules, troubleshooting. |
| `scripts/post_linkedin.py` | The canonical CLI (standard library only). |
| `scripts/stage_draft.py` | Archives each draft into `<workspace>/posts/YYYY-MM-DD-<slug>.md`; prints only the path; never overwrites without `--force`; `--list` shows what is staged. |
| `scripts/doctor.py` | Read-only setup check: Python version, skill root, resolved `.env`, required/optional keys (masked), `posts/` location. `--check-api` makes one live request and skips politely when there is no network. |
| `tests/test_post_linkedin.py` | Offline suite for the bundle; skips the repository-specific tests when the folder is used standalone from a zip. |
| `.env.example`, `requirements.txt` | Configuration template, and a file that says (accurately) that nothing needs installing. |

### How the root `post_linkedin.py` relates to it

The root file is a **thin loader**, not a second copy: it reads
`linkedin-publisher/scripts/post_linkedin.py` and executes that source into its own globals,
injecting `__skill_root__` so the bundle folder — not the file's location — decides where `.env` is
looked for. Because `main()` resolves its names in the root module's namespace, existing call sites
and `unittest.mock.patch.object(post_linkedin, 'ComposioAPI', FakeAPI)` keep working, and the two
entry points can never drift apart. Both run identically:

```bash
python3 post_linkedin.py --dry-run --file posts/draft.md --json
python3 linkedin-publisher/scripts/post_linkedin.py --dry-run --file posts/draft.md --json
```

Install the bundle into a workspace by copying the folder in, or by zipping it and uploading it as a
skill — `linkedin-publisher/README.md` walks through both.

## 8. Running the tests

```bash
cd linkedin-automation-gungun

# Root suite: file parsing + CLI behaviour against the loader (offline, no network)
python3 -m unittest test_post_file -v

# Bundle suite: env handling, --json, --max-chars, staging, urllib error mapping (offline)
python3 -m unittest discover -s linkedin-publisher/tests -t linkedin-publisher/tests -v

# Live read-only integration check (requires a real .env and a connected account)
python3 test_composio_conn.py
```

Both offline suites report `OK` with zero failures and zero errors and make no network calls.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `COMPOSIO_API_KEY is missing from .env` | Create `.env` with the required keys (see §2) — in the project root or `linkedin-publisher/`. `python3 linkedin-publisher/scripts/doctor.py` says which file it found. |
| `Env file not found: ...` | The `--env-file` path is wrong, or `LINKEDIN_PUBLISHER_ENV_FILE` points at a file that no longer exists. |
| `Composio HTTP 401/403` | The API key is wrong or belongs to another project — re-copy it from the dashboard. |
| `Network error contacting Composio` | No internet access or the endpoint is blocked; check connectivity and retry once. |
| `No ACTIVE LinkedIn connection matches COMPOSIO_USER_ID` | Re-run `conn_linkedin_composio.py` and authorize in the browser, making sure the connection was created for the same `COMPOSIO_USER_ID`. |
| `Multiple ACTIVE LinkedIn accounts belong to this user` | Set `COMPOSIO_CONNECTED_ACCOUNT_ID` in `.env` to one of the listed account IDs. |
| `Could not retrieve LinkedIn member ID automatically` / no author URN | Set `LINKEDIN_AUTHOR_URN=urn:li:person:<your-member-id>` in `.env`. |
| `Post is N characters, M over the 3000-character limit` | Shorten the draft by at least M characters (LinkedIn's limit). `--max-chars` changes the guard, not the limit. |
| `Unsupported post file type` | Only `.txt`, `.md`, and `.docx` are supported — convert or copy the text into one of those. |
| Posting action absent from catalog | The Composio tool catalog may have changed; run `python3 post_linkedin.py --inspect` / re-check the dashboard for the current slug. |
