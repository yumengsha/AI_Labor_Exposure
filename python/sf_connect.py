"""
sf_connect.py
=============
Shared Snowflake connection helper used by every Python script in this project.

Supports TWO authentication modes, chosen by the SNOWFLAKE_AUTHENTICATOR env var:

  1. externalbrowser  (default) - interactive SSO. A browser window opens for
     you to log in. Great for running things by hand. CANNOT run unattended.

  2. key-pair (JWT)    - unattended / automated. No browser, no password, no
     MFA prompt. This is what a scheduled refresh job must use. Set:
         SNOWFLAKE_AUTHENTICATOR=snowflake_jwt
         SNOWFLAKE_PRIVATE_KEY_PATH=/secure/path/rsa_key.p8
         SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=...   (only if the key is encrypted)

Why key-pair for automation?
  Snowflake is phasing out password auth for service accounts (blocked for all
  non-human users by ~Aug-Oct 2026). Key-pair auth on a TYPE=SERVICE user is the
  supported, non-interactive method. See sql/07_create_service_user.sql for the
  one-time setup of the service user + public key.

This module NEVER stores or logs secrets. It only reads env vars and returns a
live connection object.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def load_env() -> None:
    """Load a local .env (one level up from python/) if python-dotenv exists."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass  # env vars may already be exported in the shell / CI secrets


def _load_private_key(path: str, passphrase: str | None) -> bytes:
    """Read a PEM private key and return DER bytes for the connector."""
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        sys.exit("ERROR: key-pair auth needs the 'cryptography' package.\n"
                 "Run: pip install -r requirements.txt")

    key_path = Path(path).expanduser()
    if not key_path.exists():
        sys.exit(f"ERROR: SNOWFLAKE_PRIVATE_KEY_PATH not found: {key_path}")

    with open(key_path, "rb") as f:
        p_key = serialization.load_pem_private_key(
            f.read(),
            password=passphrase.encode() if passphrase else None,
            backend=default_backend(),
        )
    # The connector wants the key as DER-encoded PKCS8 bytes.
    return p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_connection(schema: str | None = None):
    """Return a live Snowflake connection based on environment variables.

    Common vars:
        SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_ROLE,
        SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA
    Auth:
        SNOWFLAKE_AUTHENTICATOR = externalbrowser | snowflake_jwt
        (jwt) SNOWFLAKE_PRIVATE_KEY_PATH, SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
    """
    load_env()
    try:
        import snowflake.connector
    except ImportError:
        sys.exit("ERROR: snowflake-connector-python not installed.\n"
                 "Run: pip install -r requirements.txt")

    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    if not account or not user:
        sys.exit("ERROR: SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER must be set "
                 "(copy .env.example to .env).")

    authenticator = os.getenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser").strip()

    params = {
        "account": account,
        "user": user,
        "role": os.getenv("SNOWFLAKE_ROLE"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "AI_LABOR_WH"),
        "database": os.getenv("SNOWFLAKE_DATABASE", "AI_LABOR_ANALYTICS"),
        "schema": schema or os.getenv("SNOWFLAKE_SCHEMA", "RAW"),
    }

    if authenticator in ("snowflake_jwt", "keypair", "key_pair"):
        # Unattended key-pair auth.
        key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
        if not key_path:
            sys.exit("ERROR: SNOWFLAKE_AUTHENTICATOR=snowflake_jwt requires "
                     "SNOWFLAKE_PRIVATE_KEY_PATH.")
        passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None
        params["authenticator"] = "snowflake_jwt"
        params["private_key"] = _load_private_key(key_path, passphrase)
        auth_desc = f"key-pair (jwt) with key {key_path}"
    else:
        # Interactive browser SSO (no password).
        params["authenticator"] = "externalbrowser"
        auth_desc = "external browser SSO"

    # Drop None values so the connector uses its defaults.
    params = {k: v for k, v in params.items() if v is not None}

    print(f"Connecting to '{account}' as '{user}' via {auth_desc} ...")
    return snowflake.connector.connect(**params)
