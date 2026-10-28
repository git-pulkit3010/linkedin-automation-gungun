---
name: linkedin-posting
description: Use when drafting, previewing, or publishing a LinkedIn text post through this project's Composio connection, including posts sourced from txt, md, or docx files.
---

# LinkedIn posting

Use `/home/vagrant/projects/linkedin_automation_gungun/venv/bin/python` with `/home/vagrant/projects/linkedin_automation_gungun/post_linkedin.py`.

## Inputs

Use either inline text or one local file as the post body. Supported files are UTF-8 `.txt` and `.md`, and `.docx`. The file content becomes the LinkedIn post text; a file is not uploaded as an attachment. Markdown is posted as literal text. `--extra` accepts an optional JSON object of additional Composio post fields.

```bash
/home/vagrant/projects/linkedin_automation_gungun/venv/bin/python /home/vagrant/projects/linkedin_automation_gungun/post_linkedin.py --dry-run --file "/absolute/path/to/draft.docx"
/home/vagrant/projects/linkedin_automation_gungun/venv/bin/python /home/vagrant/projects/linkedin_automation_gungun/post_linkedin.py --publish --file "/absolute/path/to/draft.docx"
```

For inline text, use `--dry-run "POST TEXT"` or `--publish "POST TEXT"`. For tool schema inspection, use `--inspect`. For extra fields, append `--extra '{"visibility": "CONNECTIONS"}'` to the dry run and publish commands as needed.

## Approval and execution

1. Draft the post or read the supplied file. Run `--dry-run` to inspect the exact post text and arguments that would be sent. A dry run never publishes.
2. Show the final text and any extra fields to the user. Obtain explicit approval of that specific post and target account before publishing.
3. If publishing from a file, confirm its content still matches the approved preview. Run the matching `--publish` command only after approval.
4. Report the command result. A successful Composio response should be checked on the LinkedIn profile for visibility.

Do not publish merely because the user asked to set up or test this skill. Do not edit the posting script during normal skill use; use its CLI arguments.
