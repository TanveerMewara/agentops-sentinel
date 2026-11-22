"""Local development bootstrap and service launcher for AgentOps Sentinel."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "scripts"))

import native_postgres
from sentinel.database import Database
from sentinel.security import digest_key


CONFIG = ROOT / ".local" / "sentinel-dev.json"
ROLES = ("admin", "developer", "reviewer", "worker")


def load_config():
    if not CONFIG.exists():
        raise RuntimeError("Run scripts/dev.py setup first.")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def setup():
    native_postgres.setup()
    if not CONFIG.exists():
        keys = {}
        for role in ROLES:
            prefix = secrets.token_hex(6)
            keys[role] = f"snt_{prefix}_{secrets.token_urlsafe(32)}"
        config = {
            "organization_id": str(uuid4()),
            "organization_name": "Sentinel Local Development",
            "auth_pepper": secrets.token_urlsafe(48),
            "credential_encryption_key": base64.urlsafe_b64encode(
                secrets.token_bytes(32)
            ).decode("ascii"),
            "keys": keys,
        }
        CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    config = load_config()
    if "credential_encryption_key" not in config:
        config["credential_encryption_key"] = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii")
        CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    database = Database(native_postgres.dsn())
    database.migrate()
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO sentinel_organizations (organization_id, name)
               VALUES (%s, %s) ON CONFLICT (organization_id) DO NOTHING""",
            (config["organization_id"], config["organization_name"]),
        )
        for role, token in config["keys"].items():
            key_prefix = "_".join(token.split("_", 2)[:2])
            connection.execute(
                """INSERT INTO sentinel_api_keys (
                       api_key_id, organization_id, key_prefix, key_digest, label, role
                   ) VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (key_prefix) DO NOTHING""",
                (uuid4(), config["organization_id"], key_prefix,
                 digest_key(token, config["auth_pepper"]), f"Local {role}", role),
            )
    print("Local Sentinel database, organization, and API keys are ready.")
    print("Use scripts/dev.py show-keys to display the local-only credentials.")


def child_environment():
    config = load_config()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC)
    environment["SENTINEL_DATABASE_URL"] = native_postgres.dsn()
    environment["SENTINEL_LESSON_DATABASE_URL"] = native_postgres.dsn()
    environment["SENTINEL_AUTH_PEPPER"] = config["auth_pepper"]
    environment["SENTINEL_CREDENTIAL_ENCRYPTION_KEY"] = config[
        "credential_encryption_key"
    ]
    environment["SENTINEL_BOOKING_SERVICE_URL"] = "http://127.0.0.1:8002"
    environment["SENTINEL_API_URL"] = "http://127.0.0.1:8000"
    environment["SENTINEL_WORKER_API_KEY"] = config["keys"]["worker"]
    return environment


def serve(component):
    native_postgres.start()
    environment = child_environment()
    if component == "api":
        command = [sys.executable, "-m", "uvicorn", "sentinel.asgi:app",
                   "--app-dir", "src", "--host", "127.0.0.1", "--port", "8000"]
    elif component == "booking":
        command = [sys.executable, "-m", "uvicorn", "lessons.booking_api_persistent:app",
                   "--host", "127.0.0.1", "--port", "8002"]
    else:
        command = [sys.executable, "-m", "sentinel.worker"]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def show_keys():
    config = load_config()
    print("Local-only API keys. Do not commit or share them:")
    for role, token in config["keys"].items():
        print(f"{role:9} {token}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["setup", "serve-api", "serve-booking", "serve-worker", "worker-once", "show-keys"],
    )
    args = parser.parse_args()
    if args.command == "setup":
        setup()
    elif args.command == "show-keys":
        show_keys()
    elif args.command == "worker-once":
        setup()
        environment = child_environment()
        subprocess.run([sys.executable, "-c",
                        "from sentinel.worker import from_environment; print('Processed:', from_environment().run_once())"],
                       cwd=ROOT, env=environment, check=True)
    else:
        setup()
        serve(args.command.removeprefix("serve-"))


if __name__ == "__main__":
    main()
