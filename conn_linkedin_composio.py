
import os
from dotenv import load_dotenv
from composio import Composio

load_dotenv()

api_key = os.environ["COMPOSIO_API_KEY"]
user_id = os.environ["COMPOSIO_USER_ID"]

auth_config_id = os.environ["LINKEDIN_AUTH_CONFIG_ID"]

composio = Composio(api_key=api_key)

connection = composio.connected_accounts.link(
    user_id=user_id,
    auth_config_id=auth_config_id,
)

print("Open this URL to connect LinkedIn:")
print(connection.redirect_url)
