from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .schemas import AgentCreate, AgentToolGrantCreate, ToolCreate
from .security import Principal


def agent_view(row: dict) -> dict:
    return {
        key: row[key]
        for key in (
            "agent_id", "slug", "display_name", "description", "status",
            "created_at", "updated_at",
        )
    }


def tool_view(row: dict) -> dict:
    return {
        key: row[key]
        for key in (
            "tool_id", "name", "version", "description", "input_schema",
            "output_schema", "risk_level", "approval_mode", "status",
            "created_at", "updated_at",
        )
    }


def add_registry_event(connection, principal: Principal, resource_type: str,
                       resource_id, event_type: str, details: dict):
    connection.execute(
        """INSERT INTO sentinel_registry_events (
               organization_id, resource_type, resource_id, event_type, details, actor_key_id
           ) VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            principal.organization_id, resource_type, resource_id, event_type,
            Jsonb(details), principal.api_key_id,
        ),
    )


def create_agent(database, principal: Principal, body: AgentCreate) -> tuple[dict, bool]:
    with database.connect() as connection:
        row = connection.execute(
            """INSERT INTO sentinel_agents (
                   agent_id, organization_id, slug, display_name, description, created_by_key_id
               ) VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (organization_id, slug) DO NOTHING RETURNING *""",
            (
                uuid4(), principal.organization_id, body.slug, body.display_name,
                body.description, principal.api_key_id,
            ),
        ).fetchone()
        created = row is not None
        if not created:
            row = connection.execute(
                """SELECT * FROM sentinel_agents
                   WHERE organization_id=%s AND slug=%s""",
                (principal.organization_id, body.slug),
            ).fetchone()
            if (row["display_name"], row["description"]) != (
                body.display_name, body.description
            ):
                raise HTTPException(409, "Agent slug already represents different metadata.")
        else:
            add_registry_event(
                connection, principal, "agent", row["agent_id"], "agent.registered",
                {"slug": row["slug"]},
            )
    return agent_view(row), created


def list_agents(database, principal: Principal) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT * FROM sentinel_agents WHERE organization_id=%s
               ORDER BY created_at, agent_id""",
            (principal.organization_id,),
        ).fetchall()
    return [agent_view(row) for row in rows]


def create_tool(database, principal: Principal, body: ToolCreate) -> tuple[dict, bool]:
    contract = body.model_dump()
    with database.connect() as connection:
        row = connection.execute(
            """INSERT INTO sentinel_tools (
                   tool_id, organization_id, name, version, description,
                   input_schema, output_schema, risk_level, approval_mode, created_by_key_id
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (organization_id, name, version) DO NOTHING RETURNING *""",
            (
                uuid4(), principal.organization_id, body.name, body.version,
                body.description, Jsonb(body.input_schema), Jsonb(body.output_schema),
                body.risk_level, body.approval_mode, principal.api_key_id,
            ),
        ).fetchone()
        created = row is not None
        if not created:
            row = connection.execute(
                """SELECT * FROM sentinel_tools
                   WHERE organization_id=%s AND name=%s AND version=%s""",
                (principal.organization_id, body.name, body.version),
            ).fetchone()
            comparable = {
                key: row[key]
                for key in (
                    "name", "version", "description", "input_schema", "output_schema",
                    "risk_level", "approval_mode",
                )
            }
            if comparable != contract:
                raise HTTPException(409, "Tool name and version already represent another contract.")
        else:
            add_registry_event(
                connection, principal, "tool", row["tool_id"], "tool.registered",
                {"name": row["name"], "version": row["version"]},
            )
    return tool_view(row), created


def list_tools(database, principal: Principal) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT * FROM sentinel_tools WHERE organization_id=%s
               ORDER BY name, version, tool_id""",
            (principal.organization_id,),
        ).fetchall()
    return [tool_view(row) for row in rows]


def grant_tool(database, principal: Principal, agent_id: str, tool_id: str,
               body: AgentToolGrantCreate) -> dict:
    with database.connect() as connection:
        agent = connection.execute(
            """SELECT * FROM sentinel_agents
               WHERE agent_id=%s AND organization_id=%s FOR UPDATE""",
            (agent_id, principal.organization_id),
        ).fetchone()
        tool = connection.execute(
            """SELECT * FROM sentinel_tools
               WHERE tool_id=%s AND organization_id=%s FOR UPDATE""",
            (tool_id, principal.organization_id),
        ).fetchone()
        if agent is None or tool is None:
            raise HTTPException(404, "Agent or tool not found.")
        if agent["status"] != "active" or tool["status"] != "active":
            raise HTTPException(409, "Disabled agents or tools cannot receive grants.")
        existing = connection.execute(
            """SELECT * FROM sentinel_agent_tools
               WHERE agent_id=%s AND tool_id=%s FOR UPDATE""",
            (agent["agent_id"], tool["tool_id"]),
        ).fetchone()
        if existing is not None and existing["max_calls_per_run"] == body.max_calls_per_run:
            return existing
        event_type = "agent_tool_grant.updated" if existing else "agent_tool_grant.created"
        row = connection.execute(
            """INSERT INTO sentinel_agent_tools (
                   agent_id, tool_id, organization_id, max_calls_per_run, granted_by_key_id
               ) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (agent_id, tool_id) DO UPDATE SET
                   max_calls_per_run=EXCLUDED.max_calls_per_run,
                   granted_by_key_id=EXCLUDED.granted_by_key_id,
                   granted_at=now()
               RETURNING *""",
            (
                agent["agent_id"], tool["tool_id"], principal.organization_id,
                body.max_calls_per_run, principal.api_key_id,
            ),
        ).fetchone()
        add_registry_event(
            connection, principal, "agent_tool_grant", agent["agent_id"], event_type,
            {"tool_id": str(tool["tool_id"]), "max_calls_per_run": body.max_calls_per_run},
        )
    return row


def list_agent_tools(database, principal: Principal, agent_id: str) -> list[dict]:
    with database.connect() as connection:
        agent = connection.execute(
            """SELECT agent_id FROM sentinel_agents
               WHERE agent_id=%s AND organization_id=%s""",
            (agent_id, principal.organization_id),
        ).fetchone()
        if agent is None:
            raise HTTPException(404, "Agent not found.")
        rows = connection.execute(
            """SELECT agent_id, tool_id, max_calls_per_run, granted_at
               FROM sentinel_agent_tools WHERE agent_id=%s ORDER BY granted_at, tool_id""",
            (agent["agent_id"],),
        ).fetchall()
    return rows


def list_registry_events(database, principal: Principal, limit: int) -> list[dict]:
    with database.connect() as connection:
        return connection.execute(
            """SELECT event_id, resource_type, resource_id, event_type, details, created_at
               FROM sentinel_registry_events WHERE organization_id=%s
               ORDER BY event_id DESC LIMIT %s""",
            (principal.organization_id, limit),
        ).fetchall()
