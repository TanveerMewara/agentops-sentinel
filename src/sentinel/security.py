from dataclasses import dataclass
import hashlib
import hmac

from fastapi import Header, HTTPException, Request
from .request_limits import consume_request


@dataclass(frozen=True)
class Principal:
    api_key_id: str
    organization_id: str
    role: str
    auth_kind: str = 'api_key'
    member_id: str | None = None


def digest_key(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def authenticate(request: Request, x_api_key: str | None = Header(default=None),
                 x_csrf_token: str | None = Header(default=None,alias='X-CSRF-Token')) -> Principal:
    if not x_api_key:
        token=request.cookies.get('sentinel_session')
        if not token: raise HTTPException(401,"A valid API key or member session is required.")
        with request.app.state.database.connect() as connection:
            record=connection.execute("""SELECT sessions.session_id,sessions.csrf_digest,
              members.member_id::text,members.actor_key_id::text AS api_key_id,
              members.organization_id::text,members.role FROM sentinel_member_sessions sessions
              JOIN sentinel_members members ON members.member_id=sessions.member_id
                AND members.organization_id=sessions.organization_id
              WHERE sessions.token_digest=%s AND sessions.revoked_at IS NULL
                AND sessions.expires_at>now() AND members.status='active'""",
              (digest_key(token,request.app.state.settings.auth_pepper),)).fetchone()
            if record is None: raise HTTPException(401,'Member session is invalid or expired.')
            if request.method not in ('GET','HEAD','OPTIONS'):
                expected=digest_key(x_csrf_token or '',request.app.state.settings.auth_pepper)
                if not x_csrf_token or not hmac.compare_digest(record['csrf_digest'],expected):
                    raise HTTPException(403,'A valid X-CSRF-Token header is required.')
            connection.execute('UPDATE sentinel_member_sessions SET last_seen_at=now() WHERE session_id=%s',(record['session_id'],))
        return Principal(record['api_key_id'],record['organization_id'],record['role'],'session',record['member_id'])
    if not x_api_key.startswith("snt_"):
        raise HTTPException(401, "A valid X-API-Key header is required.")
    prefix = x_api_key.split("_", 2)[:2]
    if len(prefix) != 2:
        raise HTTPException(401, "Invalid API key.")
    key_prefix = "_".join(prefix)
    with request.app.state.database.connect() as connection:
        record = connection.execute(
            """SELECT api_key_id::text, organization_id::text, role, key_digest
               FROM sentinel_api_keys
               WHERE key_prefix = %s AND revoked_at IS NULL
                 AND (expires_at IS NULL OR expires_at>now())""",
            (key_prefix,),
        ).fetchone()
        expected = digest_key(x_api_key, request.app.state.settings.auth_pepper)
        if record is None or not hmac.compare_digest(record["key_digest"], expected):
            raise HTTPException(401, "Invalid API key.")
        settings = request.app.state.settings
        allowed, retry_seconds = consume_request(connection, record["api_key_id"],
                                                settings.requests_per_window, settings.request_window_seconds)
    # Commit the counter, including blocked requests, before raising an error.
    if not allowed:
        raise HTTPException(429, "API key request limit exceeded.", headers={"Retry-After": str(retry_seconds)})
    return Principal(record["api_key_id"], record["organization_id"], record["role"])


def require_roles(*roles: str):
    def check(principal: Principal) -> Principal:
        if principal.role not in roles:
            raise HTTPException(403, "This identity cannot perform that action.")
        return principal
    return check
