from langfuse.openai import openai
from langfuse import get_client
import os
from dotenv import load_dotenv

load_dotenv()

print(f"Public Key: {os.environ.get('LANGFUSE_PUBLIC_KEY', 'NOT SET')}")
print(
    f"Secret Key: {os.environ.get('LANGFUSE_SECRET_KEY', 'NOT SET')[:10]}..."
)  # Only first 10 chars for security
print(f"Base URL: {os.environ.get('LANGFUSE_BASE_URL', 'NOT SET')}")

langfuse = get_client()

# Verify connection
if langfuse.auth_check():
    print("Langfuse client is authenticated and ready!")
else:
    print("Authentication failed. Please check your credentials and host.")

completion = openai.chat.completions.create(
    name="test-chat",
    model="gpt-4o-mini",
    messages=[
        {
            "role": "system",
            "content": "You are a very accurate calculator. You output only the result of the calculation.",
        },
        {"role": "user", "content": "1 + 1 = "},
    ],
    metadata={"someMetadataKey": "someValue"},
)
