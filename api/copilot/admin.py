"""Admin tasks, run on the server by hand.

    python -m copilot.admin reset-password <email>

There is no self-service password reset in v1. This sets a new random
password and prints it once, for the admin to pass on to the user.
"""

import argparse
import sys

from copilot.api import security
from copilot.config import ConfigError, load_settings
from copilot.db import connect


def reset_password(conn, email: str) -> str | None:
    """Returns the new password, or None when no account has that email."""
    password = security.random_password()
    row = conn.execute(
        "update users set password_hash = %s where lower(email) = lower(%s) returning id",
        (security.hash_password(password), email.strip()),
    ).fetchone()
    return password if row else None


def main(argv: list[str] | None = None, conn=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot.admin", description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    reset = actions.add_parser("reset-password", help="give a user a new random password")
    reset.add_argument("email")
    args = parser.parse_args(argv)

    own = conn is None
    if own:
        try:
            conn = connect(load_settings())
        except ConfigError as error:
            print(error, file=sys.stderr)
            return 2
    try:
        password = reset_password(conn, args.email)
        conn.commit()
    finally:
        if own:
            conn.close()
    if password is None:
        print(f"No account has the email {args.email}.", file=sys.stderr)
        return 1
    print(f"New password for {args.email}: {password}")
    print("Pass it on privately. It is not stored anywhere in readable form.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
