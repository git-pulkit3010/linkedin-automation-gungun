# LinkedIn Posting Skill

This skill allows the agent to post content to LinkedIn using a deterministic Python wrapper around the Composio API.

## Description
Automates the process of publishing approved text to a linked LinkedIn profile. This tool MUST only be used after the user has explicitly approved the final text of the post.

## Usage
To post to LinkedIn, execute the following command using the project's virtual environment:

`/home/vagrant/projects/linkedin_automation_gungun/venv/bin/python /home/vagrant/projects/linkedin_automation_gungun/post_linkedin.py "THE_POST_CONTENT"`

## Constraints
1. **Human Approval Required**: Never call this tool unless the user has said "Approved", "Go ahead", or similar explicit confirmation of the specific text.
2. **Deterministic**: Do not modify the `post_linkedin.py` script. Only pass the approved text as an argument.
3. **Environment**: Always use the full path to the venv python interpreter to ensure dependencies are loaded.

## Workflow
1. Draft the post content.
2. Present the draft to the user.
3. Await explicit approval.
4. Execute the command: `/home/vagrant/projects/linkedin_automation_gungun/venv/bin/python /home/vagrant/projects/linkedin_automation_gungun/post_linkedin.py "Approved Text"`
