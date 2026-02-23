"""Shared Bluesky client factory to avoid duplicate login boilerplate."""
import os
from atproto import Client


def create_bluesky_client() -> Client:
    """Create and authenticate a Bluesky client using app password."""
    username = os.getenv("BLUESKY_USERNAME")
    app_password = os.getenv("BLUESKY_APP_PASSWORD")
    if not all([username, app_password]):
        raise ValueError(
            "Missing Bluesky credentials. "
            "Set BLUESKY_USERNAME and BLUESKY_APP_PASSWORD environment variables."
        )
    client = Client()
    client.login(username, app_password)
    print(f"Logged into Bluesky as @{username}")
    return client
