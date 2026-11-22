"""One-time setup for a hosted AgentOps Sentinel database.

Applies migrations, creates one organization and one API key per role, and
prints the keys once. Nothing is written to disk.

    # 1. Generate the two server secrets (store them in your host's env settings):
    python scripts/bootstrap_hosted.py secrets

    # 2. With SENTINEL_DATABASE_URL and SENTINEL_AUTH_PEPPER set, seed the database:
    python scripts/bootstrap_hosted.py seed --organization "My Team"

Run locally with PYTHONPATH=src, or inside the deployed container (e.g. a Render
shell), where the sentinel package is already installed.
"""
import argparse
import base64
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ROLES = ("admin", "developer", "reviewer", "worker")


def print_secrets() -> None:
    print("SENTINEL_AUTH_PEPPER=" + secrets.token_urlsafe(48))
    print(
        "SENTINEL_CREDENTIAL_ENCRYPTION_KEY="
        + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    )
    print("\nStore both in the API service's environment. Changing the pepper later "
          "invalidates every API key; changing the encryption key makes stored "
          "provider credentials unreadable.")


def seed(organization_name: str) -> None:
    from sentinel.database import Database
    from sentinel.security import digest_key

    database_url = os.environ.get("SENTINEL_DATABASE_URL")
    pepper = os.environ.get("SENTINEL_AUTH_PEPPER")
    if not database_url or not pepper:
        raise SystemExit("Set SENTINEL_DATABASE_URL and SENTINEL_AUTH_PEPPER first.")

    database = Database(database_url)
    database.migrate()
    organization_id = uuid4()
    keys = {role: f"snt_{secrets.token_hex(6)}_{secrets.token_urlsafe(32)}" for role in ROLES}
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sentinel_organizations (organization_id, name) VALUES (%s, %s)",
            (organization_id, organization_name),
        )
        for role, token in keys.items():
            key_prefix = "_".join(token.split("_", 2)[:2])
            connection.execute(
                """INSERT INTO sentinel_api_keys (
                       api_key_id, organization_id, key_prefix, key_digest, label, role
                   ) VALUES (%s, %s, %s, %s, %s, %s)""",
                (uuid4(), organization_id, key_prefix, digest_key(token, pepper),
                 f"Hosted {role}", role),
            )
    print(f"Migrations applied. Organization '{organization_name}' = {organization_id}")
    print("API keys (shown once - store them in a password manager):")
    for role, token in keys.items():
        print(f"  {role:<10} {token}")
    print("\nPut the worker key in the worker service as SENTINEL_WORKER_API_KEY.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("secrets", help="Print new server secrets.")
    seed_parser = commands.add_parser("seed", help="Migrate and create an organization with keys.")
    seed_parser.add_argument("--organization", default="AgentOps Sentinel")
    args = parser.parse_args()
    if args.command == "secrets":
        print_secrets()
    else:
        seed(args.organization)


if __name__ == "__main__":
    main()
