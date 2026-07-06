"""
test_connection.py
==================
Verify that the Snowflake connection works, then run:

    SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE();

Authentication is handled by the shared sf_connect module and chosen via
SNOWFLAKE_AUTHENTICATOR:
    * externalbrowser (default) - opens a browser for interactive SSO login.
    * snowflake_jwt             - unattended key-pair auth (for automation).
Either way, NO password is stored.

Setup
-----
1. pip install -r requirements.txt
2. Copy .env.example to .env and fill in your account + user.
3. python python/test_connection.py
"""

from __future__ import annotations

import sys

from sf_connect import get_connection


def main() -> None:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), "
            "CURRENT_WAREHOUSE(), CURRENT_DATABASE()"
        )
        user, role, warehouse, database = cur.fetchone()

        print("\n" + "=" * 50)
        print("CONNECTION SUCCESSFUL")
        print("=" * 50)
        print(f"  CURRENT_USER()      : {user}")
        print(f"  CURRENT_ROLE()      : {role}")
        print(f"  CURRENT_WAREHOUSE() : {warehouse}")
        print(f"  CURRENT_DATABASE()  : {database}")
        print("=" * 50)
        cur.close()
    except Exception as exc:  # noqa: BLE001 - show any connection error clearly
        sys.exit(f"\nCONNECTION FAILED: {exc}")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
