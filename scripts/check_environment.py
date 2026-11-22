"""Read-only readiness check for the selected native PostgreSQL setup."""
import argparse
import shutil
import subprocess


def check_docker():
    if shutil.which("docker") is None:
        print("Optional Docker: not installed.")
        return
    try:
        result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        print("Optional Docker: did not respond within 15 seconds.")
        return
    print("Optional Docker: responding." if result.returncode == 0 else "Optional Docker: unavailable.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="Also check optional Docker availability.")
    args = parser.parse_args()
    try:
        import native_postgres
        with native_postgres.psycopg.connect(native_postgres.dsn()) as connection:
            version = connection.execute("SHOW server_version").fetchone()[0]
        print(f"PASS: native PostgreSQL {version} responds on localhost:55432.")
        print("Run scripts/native_postgres.py check to verify persistence; readiness alone is not proof.")
        ready = True
    except (ImportError, OSError, RuntimeError):
        print("NOT READY: install dependencies and run scripts/native_postgres.py setup.")
        ready = False
    except Exception as error:
        # Do not expose configuration or connection strings in diagnostics.
        print(f"NOT READY: PostgreSQL connection failed ({type(error).__name__}).")
        ready = False
    if args.docker:
        check_docker()
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
