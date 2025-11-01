"""Configuration and environment variable loading."""

import os
from dotenv import load_dotenv


load_dotenv()


def get_credentials():
    """Load and validate required credentials from environment."""
    email = os.getenv("ZEPPEMAIL")
    password = os.getenv("ZEPP_PASSWORD")
    
    if not email or not password:
        raise SystemExit("❌ Faltan ZEPPEMAIL o ZEPP_PASSWORD en el entorno")
    
    return email, password


def get_openai_api_key():
    """Get OpenAI API key from environment."""
    return os.getenv("OPENAI_API_KEY")

