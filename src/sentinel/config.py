from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str
    auth_pepper: str
    booking_service_url: str
    credential_encryption_key: str
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )
    execution_lease_seconds: int = 30
    model_timeout_seconds: int = 20
    requests_per_window: int = 600
    request_window_seconds: int = 60

    def __post_init__(self):
        if type(self.requests_per_window) is not int or not 1 <= self.requests_per_window <= 100000:
            raise ValueError("Request limit must be between 1 and 100000.")
        if type(self.request_window_seconds) is not int or not 1 <= self.request_window_seconds <= 3600:
            raise ValueError("Request window must be between 1 and 3600 seconds.")

    @classmethod
    def from_environment(cls) -> "Settings":
        database_url = os.environ.get("SENTINEL_DATABASE_URL")
        auth_pepper = os.environ.get("SENTINEL_AUTH_PEPPER")
        credential_encryption_key = os.environ.get("SENTINEL_CREDENTIAL_ENCRYPTION_KEY")
        if not database_url or not auth_pepper or not credential_encryption_key:
            raise RuntimeError(
                "SENTINEL_DATABASE_URL, SENTINEL_AUTH_PEPPER, and "
                "SENTINEL_CREDENTIAL_ENCRYPTION_KEY are required. "
                "Use scripts/dev.py for local development."
            )
        origins = os.environ.get(
            "SENTINEL_ALLOWED_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000",
        )
        try:
            execution_lease_seconds = int(
                os.environ.get("SENTINEL_EXECUTION_LEASE_SECONDS", "30")
            )
        except ValueError as error:
            raise RuntimeError("SENTINEL_EXECUTION_LEASE_SECONDS must be an integer.") from error
        if execution_lease_seconds < 3 or execution_lease_seconds > 3600:
            raise RuntimeError("SENTINEL_EXECUTION_LEASE_SECONDS must be between 3 and 3600.")
        try:
            model_timeout_seconds = int(os.environ.get("SENTINEL_MODEL_TIMEOUT_SECONDS", "20"))
        except ValueError as error:
            raise RuntimeError("SENTINEL_MODEL_TIMEOUT_SECONDS must be an integer.") from error
        if model_timeout_seconds < 1 or model_timeout_seconds > 120:
            raise RuntimeError("SENTINEL_MODEL_TIMEOUT_SECONDS must be between 1 and 120.")
        try:
            request_limit = int(os.environ.get("SENTINEL_REQUESTS_PER_WINDOW", "600"))
            request_window = int(os.environ.get("SENTINEL_REQUEST_WINDOW_SECONDS", "60"))
            if not 1 <= request_limit <= 100000 or not 1 <= request_window <= 3600:
                raise ValueError()
        except ValueError:
            raise RuntimeError("Request limit/window configuration is invalid.") from None
        return cls(
            database_url=database_url,
            auth_pepper=auth_pepper,
            credential_encryption_key=credential_encryption_key,
            booking_service_url=os.environ.get(
                "SENTINEL_BOOKING_SERVICE_URL", "http://127.0.0.1:8002"
            ).rstrip("/"),
            allowed_origins=tuple(
                origin.strip().rstrip("/")
                for origin in origins.split(",")
                if origin.strip()
            ),
            execution_lease_seconds=execution_lease_seconds,
            model_timeout_seconds=model_timeout_seconds,
            requests_per_window=request_limit,
            request_window_seconds=request_window,
        )
