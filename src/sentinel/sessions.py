"""Invitation onboarding and server-side browser sessions."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import hashlib,hmac,secrets
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field,model_validator

from .security import digest_key,require_roles

SESSION_COOKIE='sentinel_session'
CSRF_COOKIE='sentinel_csrf'


class OrganizationProfileUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    slug: str=Field(pattern=r'^[a-z][a-z0-9-]{2,49}$')
    display_name: str=Field(min_length=2,max_length=100)


class InvitationCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    handle: str=Field(pattern=r'^[a-z][a-z0-9_.-]{2,63}$')
    role: Literal['admin','developer','reviewer','worker']
    expires_in_hours: int=Field(default=48,ge=1,le=168)


class InvitationAccept(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    token: str=Field(min_length=32,max_length=300)
    display_name: str=Field(min_length=2,max_length=100)
    password: str=Field(min_length=12,max_length=128)

    @model_validator(mode='after')
    def strong_password(self):
        if len(set(self.password))<6 or not any(c.isalpha() for c in self.password) or not any(c.isdigit() for c in self.password):
            raise ValueError('Password needs varied letters and numbers.')
        return self


class LoginCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    organization_slug: str=Field(pattern=r'^[a-z][a-z0-9-]{2,49}$')
    handle: str=Field(pattern=r'^[a-z][a-z0-9_.-]{2,63}$')
    password: str=Field(min_length=1,max_length=128)


def _password(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1,dklen=32).hex()


def _preauth(connection,request,pepper,route,limit=10):
    host=request.client.host if request.client else 'unknown'
    identity=hmac.new(pepper.encode(),host.encode(),hashlib.sha256).hexdigest()
    row=connection.execute("""INSERT INTO sentinel_preauth_limits(identity_hash,route)
      VALUES (%s,%s) ON CONFLICT(identity_hash,route) DO UPDATE SET
      request_count=CASE WHEN sentinel_preauth_limits.window_started_at<now()-interval '5 minutes' THEN 1
                         ELSE sentinel_preauth_limits.request_count+1 END,
      window_started_at=CASE WHEN sentinel_preauth_limits.window_started_at<now()-interval '5 minutes' THEN now()
                             ELSE sentinel_preauth_limits.window_started_at END RETURNING request_count""",
      (identity,route)).fetchone()
    if row['request_count']>limit: raise HTTPException(429,'Too many authentication attempts.',headers={'Retry-After':'300'})


def configure_organization(database,principal,body):
    require_roles('admin')(principal)
    with database.connect() as connection:
        return connection.execute("""INSERT INTO sentinel_organization_profiles
          (organization_id,slug,display_name) VALUES (%s,%s,%s)
          ON CONFLICT(organization_id) DO UPDATE SET slug=excluded.slug,
          display_name=excluded.display_name,updated_at=now() RETURNING *""",
          (principal.organization_id,body.slug,body.display_name)).fetchone()


def create_invitation(database,pepper,principal,body):
    require_roles('admin')(principal)
    token='sni_'+secrets.token_urlsafe(32); digest=digest_key(token,pepper)
    with database.connect() as connection:
        profile=connection.execute('SELECT 1 FROM sentinel_organization_profiles WHERE organization_id=%s',(principal.organization_id,)).fetchone()
        if profile is None: raise HTTPException(409,'Configure the organization profile before inviting members.')
        existing=connection.execute('SELECT * FROM sentinel_members WHERE organization_id=%s AND handle=%s',(principal.organization_id,body.handle)).fetchone()
        if existing: raise HTTPException(409,'This member handle already exists.')
        row=connection.execute("""INSERT INTO sentinel_member_invitations
          (invitation_id,organization_id,handle,role,token_digest,expires_at,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s,now()+(%s*interval '1 hour'),%s)
          ON CONFLICT(organization_id,handle) DO UPDATE SET role=excluded.role,
          token_digest=excluded.token_digest,expires_at=excluded.expires_at,accepted_at=NULL,
          created_by_key_id=excluded.created_by_key_id,created_at=now() RETURNING *""",
          (uuid4(),principal.organization_id,body.handle,body.role,digest,body.expires_in_hours,principal.api_key_id)).fetchone()
    return {'invitation_id':row['invitation_id'],'handle':row['handle'],'role':row['role'],
            'expires_at':row['expires_at'],'token':token}


def _set_session(response,token,csrf,expires,secure):
    max_age=max(1,int((expires-datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(SESSION_COOKIE,token,max_age=max_age,httponly=True,secure=secure,samesite='strict',path='/')
    response.set_cookie(CSRF_COOKIE,csrf,max_age=max_age,httponly=False,secure=secure,samesite='strict',path='/')
    response.headers['Cache-Control']='no-store'


def _new_session(connection,member,pepper,response,secure):
    token='sns_'+secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
    expires=datetime.now(timezone.utc)+timedelta(hours=8)
    connection.execute("""INSERT INTO sentinel_member_sessions
      (session_id,member_id,organization_id,token_digest,csrf_digest,expires_at)
      VALUES (%s,%s,%s,%s,%s,%s)""",(uuid4(),member['member_id'],member['organization_id'],
      digest_key(token,pepper),digest_key(csrf,pepper),expires))
    _set_session(response,token,csrf,expires,secure)


def accept_invitation(database,pepper,request,response,body):
    digest=digest_key(body.token,pepper)
    with database.connect() as connection:
        _preauth(connection,request,pepper,'invite_accept')
        invitation=connection.execute("""SELECT * FROM sentinel_member_invitations
          WHERE token_digest=%s AND accepted_at IS NULL AND expires_at>now() FOR UPDATE""",(digest,)).fetchone()
        if invitation is None: raise HTTPException(401,'Invitation is invalid or expired.')
        salt=secrets.token_hex(16); actor_id=uuid4(); member_id=uuid4()
        connection.execute("""INSERT INTO sentinel_api_keys
          (api_key_id,organization_id,key_prefix,key_digest,label,role,key_kind)
          VALUES (%s,%s,%s,%s,%s,%s,'member_actor')""",(actor_id,invitation['organization_id'],
          'member_'+member_id.hex,'0'*64,'Member actor '+invitation['handle'],invitation['role']))
        member=connection.execute("""INSERT INTO sentinel_members
          (member_id,organization_id,handle,display_name,password_hash,password_salt,role,actor_key_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(member_id,invitation['organization_id'],
          invitation['handle'],body.display_name,_password(body.password,salt),salt,invitation['role'],actor_id)).fetchone()
        connection.execute('UPDATE sentinel_member_invitations SET accepted_at=now() WHERE invitation_id=%s',(invitation['invitation_id'],))
        _new_session(connection,member,pepper,response,request.url.scheme=='https')
    return member_view(member)


def login(database,pepper,request,response,body):
    with database.connect() as connection:
        _preauth(connection,request,pepper,'login')
        member=connection.execute("""SELECT members.* FROM sentinel_members members
          JOIN sentinel_organization_profiles profile ON profile.organization_id=members.organization_id
          WHERE profile.slug=%s AND members.handle=%s AND members.status='active'""",
          (body.organization_slug,body.handle)).fetchone()
        if member is None or not hmac.compare_digest(member['password_hash'],_password(body.password,member['password_salt'])):
            raise HTTPException(401,'Invalid organization, handle, or password.')
        connection.execute('DELETE FROM sentinel_member_sessions WHERE expires_at<=now() OR revoked_at IS NOT NULL')
        _new_session(connection,member,pepper,response,request.url.scheme=='https')
    return member_view(member)


def logout(database,pepper,request,response):
    token=request.cookies.get(SESSION_COOKIE)
    if token:
        with database.connect() as connection:
            connection.execute('UPDATE sentinel_member_sessions SET revoked_at=now() WHERE token_digest=%s AND revoked_at IS NULL',(digest_key(token,pepper),))
    response.delete_cookie(SESSION_COOKIE,path='/'); response.delete_cookie(CSRF_COOKIE,path='/')
    response.headers['Cache-Control']='no-store'
    return {'logged_out':True}


def member_view(row):
    return {'member_id':row['member_id'],'organization_id':row['organization_id'],
            'handle':row['handle'],'display_name':row['display_name'],'role':row['role'],
            'status':row['status'],'created_at':row['created_at']}


def list_members(database,principal):
    require_roles('admin')(principal)
    with database.connect() as connection:
        rows=connection.execute('SELECT * FROM sentinel_members WHERE organization_id=%s ORDER BY created_at',(principal.organization_id,)).fetchall()
    return [member_view(row) for row in rows]
