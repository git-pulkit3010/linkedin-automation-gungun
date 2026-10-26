import os
import sys
from dotenv import load_dotenv
from composio import ComposioToolSet

# Load environment variables from .env file
load_dotenv()

def main():
    if len(sys.argv) < 2:
        print("Error: No post content provided.")
        sys.exit(1)

    post_content = sys.argv[1]
    api_key = os.getenv("COMPOSIO_API_KEY")

    if not api_key:
        print("Error: COMPOSIO_API_KEY not found in .env file.")
        sys.exit(1)

    try:
        # Initialize Composio ToolSet
        toolset = ComposioToolSet(api_key=api_key)
        
        # Execute the linkedin_share_post tool
        # Note: The tool name is typically 'linkedin_share_post' in Composio
        result = toolset.execute_tool("linkedin_share_post", {
            "text": post_content
        })
        
        print(f"Successfully posted to LinkedIn: {result}")
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
