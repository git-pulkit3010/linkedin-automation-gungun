"""One-time Google Drive OAuth link for the same Composio user as LinkedIn.

Requires the optional composio and python-dotenv packages used by the LinkedIn
connection helper. Configure GOOGLEDRIVE_AUTH_CONFIG_ID in the project .env.
"""

import os

from composio import Composio
from dotenv import load_dotenv


def main():
    load_dotenv()
    composio = Composio(api_key=os.environ['COMPOSIO_API_KEY'])
    connection = composio.connected_accounts.link(
        user_id=os.environ['COMPOSIO_USER_ID'],
        auth_config_id=os.environ['GOOGLEDRIVE_AUTH_CONFIG_ID'],
    )
    print('Open this URL to connect Google Drive:')
    print(connection.redirect_url)


if __name__ == '__main__':
    main()
