from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CONTACT_EMAIL = "you@example.com"
TOOL_NAME = "citeguard"
TOOL_VERSION = "0.1"


def resolve_contact_email(email: str | None = None) -> str:
    return (email or os.getenv("CONTACT_EMAIL") or DEFAULT_CONTACT_EMAIL).strip()


def build_user_agent(email: str | None = None) -> str:
    contact = resolve_contact_email(email)
    return f"{TOOL_NAME}/{TOOL_VERSION} (mailto:{contact})"
