# LinkedIn Automation (via Composio)

A small Python toolkit for drafting, previewing, and publishing **text posts to LinkedIn** through the
[Composio](https://composio.dev) platform (Composio v3.1 REST API).

Post text can be supplied inline or read from a local `.txt`, `.md`, or `.docx` file. The script
auto-discovers the connected LinkedIn account, resolves your LinkedIn member ID (author URN), and
builds the exact post payload before anything is sent — with a strict `--dry-run` mode that never publishes.

## Project layout

| File | Purpose |
|---|---|
| `post_linkedin.py` | Main CLI: inspect, dry-run, or publish a LinkedIn post |
| `conn_linkedin_composio.py` | One-time setup: prints the URL to connect your LinkedIn account to Composio |
| `test_composio_conn.py` | Read-only end-to-end checks: API key, tool catalog, connected account, profile endpoint |
| `test_post_file.py` | Offline unit tests (file parsing + CLI behavior, no network) |
| `SKILL.md` | Agent skill definition for automated, approval-gated posting |
| `posts/` | Directory for draft post files (`.txt`, `.md`, `.docx`) |
| `.env` | Local secrets (not committed) |

---

## 1. Prerequisites

- **Python 3.10+** (developed and tested on Python 3.12)
- **pip**
- A **Composio account** — sign up at [app.composio.dev](https://app.composio.dev)
- A **LinkedIn account** you want to post as

## 2. Required API keys / credentials

Everything is configured in a single `.env` file in the project root (the scripts load
`.env` from their own directory, so keep it next to the code).

```dotenv
# --- Required (all scripts) ---
COMPOSIO_API_KEY=...              # Composio API key
COMPOSIO_USER_ID=...              # The Composio end-user ID the LinkedIn account is linked to

# --- Required only for conn_linkedin_composio.py (one-time connection) ---
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

```bash
cd linkedin_automation_gungun

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install packages
python -m pip install composio requests python-dotenv
```

Reference versions this repo was built with: `composio==0.30.0`, `requests==2.34.2`,
`python-dotenv==1.2.4` on Python 3.12.

> Only `post_linkedin.py` + `test_composio_conn.py` strictly need `requests` and `python-dotenv`
> (they call the REST API directly). `conn_linkedin_composio.py` additionally needs the
> `composio` SDK.

## 4. Connect your LinkedIn account (one-time)

```bash
python conn_linkedin_composio.py
```

This prints a **redirect URL**. Open it in a browser, log in with the LinkedIn account you want to
post from, and authorize the app. The connected account is then created in Composio under your
`COMPOSIO_USER_ID`.

## 5. Verify the setup (read-only, publishes nothing)

```bash
python test_composio_conn.py
```

Expected output ends with `READ-ONLY CHECKS PASSED`. It verifies, in order:

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

A successful publish prints the account, author URN, toolkit version, the post arguments, and the
Composio execution response (`data` + `log_id`). Always confirm the post is visible on the LinkedIn
profile.

> **Exit codes:** `0` on success, `1` on any setup/network/API error (message goes to stderr).

### Recommended workflow

1. Write your draft into `posts/draft.md` (or `.txt` / `.docx`).
2. Run the matching `--dry-run` command and review the exact post text and payload.
3. Only after approving that exact preview, run the matching `--publish` command.

## 7. Running the tests

```bash
# Offline unit tests (file parsing, CLI argument handling) — no network required
python -m unittest test_post_file -v

# Live read-only integration check (requires .env and a connected account)
python test_composio_conn.py
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `COMPOSIO_API_KEY is missing from .env` | Create `.env` next to the scripts with the required keys (see §2). |
| `Composio HTTP 401/403` | The API key is wrong or belongs to another project — re-copy it from the dashboard. |
| `No ACTIVE LinkedIn connection matches COMPOSIO_USER_ID` | Re-run `conn_linkedin_composio.py` and authorize in the browser, making sure the connection was created for the same `COMPOSIO_USER_ID`. |
| `Multiple ACTIVE LinkedIn accounts belong to this user` | Set `COMPOSIO_CONNECTED_ACCOUNT_ID` in `.env` to one of the listed account IDs. |
| `Could not retrieve LinkedIn member ID automatically` / no author URN | Set `LINKEDIN_AUTHOR_URN=urn:li:person:<your-member-id>` in `.env`. |
| `Unsupported post file type` | Only `.txt`, `.md`, and `.docx` are supported — convert or copy the text into one of those. |
| Posting action absent from catalog | The Composio tool catalog may have changed; run `python post_linkedin.py --inspect` / re-check the dashboard for the current slug. |
