#!/usr/bin/env python3
"""Read-only Composio API key, LinkedIn catalog and account verification."""
import json
import os
import sys
from post_linkedin import (ComposioAPI, SetupError, POST_SLUG, PROFILE_SLUG,
                           active_linkedin_account, author_from_profile)


def main():
    try:
        api = ComposioAPI(os.getenv('COMPOSIO_API_KEY'))
        print('1. Testing Composio API key (GET /toolkits/linkedin)...')
        toolkit = api.request('GET', '/toolkits/linkedin')
        print('   PASS: API key accepted; toolkit:', toolkit.get('slug', 'linkedin'))

        print('2. Checking current LinkedIn tools (v3.1 latest)...')
        tools = api.linkedin_tools()
        slugs = {t.get('slug') for t in tools}
        for slug in (POST_SLUG, PROFILE_SLUG):
            print('  ', 'PASS' if slug in slugs else 'MISSING', slug)
        print('   Tools found:', len(slugs))
        if POST_SLUG not in slugs:
            raise SetupError('Posting action missing from latest catalog; slugs: '
                             + ', '.join(sorted(slugs)))

        print('3. Checking linked account for COMPOSIO_USER_ID...')
        user_id = os.getenv('COMPOSIO_USER_ID', '').strip()
        account = active_linkedin_account(api, user_id)
        print('   PASS: ACTIVE LinkedIn account:', account['id'], 'user:', user_id)

        print('4. Calling LinkedIn GET_MY_INFO (read-only credential/scope test)...')
        profile = api.execute(api.tool(PROFILE_SLUG), user_id, account['id'], {})
        urn = author_from_profile(profile)
        print('   PASS: LinkedIn authenticated profile endpoint worked.')
        print('   Derived author URN:', urn or '(not available: configure LINKEDIN_AUTHOR_URN)')
        print('\nREAD-ONLY CHECKS PASSED. Posting permission is not verified; no post was published.')
        return 0
    except SetupError as exc:
        print('FAILED:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
