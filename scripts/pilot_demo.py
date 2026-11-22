"""Explicit fictional configuration; no lead, approval, booking or email writes."""
from sentinel.adapters import contract_digest

BOOKING_TOOL = {
    "name": "book_viewing", "version": "2.0.0",
    "description": "Creates one approved property viewing.",
    "input_schema": {"type": "object", "properties": {
        "customer": {"type": "string", "minLength": 1},
        "slot": {"type": "string", "minLength": 1},
        "property_id": {"type": "string", "format": "uuid"},
        "property_version": {"type": "integer", "minimum": 1}},
        "required": ["customer", "slot", "property_id", "property_version"],
        "additionalProperties": False},
    "output_schema": {"type": "object", "properties": {
        "booking_id": {"type": "string", "minLength": 1}},
        "required": ["booking_id"], "additionalProperties": False},
    "risk_level": "high", "approval_mode": "always",
}


def configure_demo(client):
    existing = next((tool for tool in client.request("/v1/tools")
                     if tool["name"] == "book_viewing" and tool["version"] == "2.0.0"), None)
    if existing:
        if existing["status"] != "active" or contract_digest(existing) != contract_digest(BOOKING_TOOL):
            raise RuntimeError("The installed booking contract differs from the demo. It was not overwritten.")
        tool = existing
    else:
        tool = client.request("/v1/tools", BOOKING_TOOL)
    agent = client.register_agent("estateflow_local_pilot", "EstateFlow local pilot",
                                  "Fictional local viewing workflow; no live calendar or email delivery.")
    client.request(f"/v1/agents/{agent['agent_id']}/tools/{tool['tool_id']}", {"max_calls_per_run": 1})
    version = client.create_version(agent["agent_id"], "1.0.0",
        "Use retrieved property evidence and the buyer's exact requested time. "
        "Request human approval before a fictional viewing. Never imply email delivery.",
        model_alias="deterministic_estateflow")
    listing = client.request("/v1/properties", {
        "external_key": "sentinel-pilot-fictional-metro-v1",
        "title": "Fictional metro apartment — local pilot",
        "description": "Fictional two-bedroom apartment beside the metro, with parking. Demo data only.",
        "city": "Jaipur", "locality": "Mansarovar", "property_type": "apartment",
        "bedrooms": 2, "bathrooms": "2.0", "price_inr": "7500000.00", "area_sqft": "1100.00",
        "amenities": ["parking", "lift"], "source_uri": "https://estateflow.example.test/pilot/metro",
        "listing_status": "active",
    })
    return {"agent_id": agent["agent_id"], "agent_version_id": version["agent_version_id"],
            "tool_id": tool["tool_id"], "property_id": listing["property"]["property_id"]}
