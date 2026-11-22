"""Legacy EstateFlow evaluation facts. Called only for its requested rules."""

RULES = frozenset({'completed_bookings', 'property_bound', 'approvals_consumed', 'review_required', 'followup_status'})


def collect_facts(connection, organization_id, run_id):
    calls = connection.execute(
        """SELECT calls.arguments, calls.requires_approval,
                  EXISTS(SELECT 1 FROM sentinel_tool_call_approvals approvals
                    WHERE approvals.tool_call_id=calls.tool_call_id
                      AND approvals.organization_id=calls.organization_id
                      AND approvals.action_hash=calls.action_hash AND approvals.state='consumed') AS consumed
           FROM sentinel_tool_calls calls JOIN sentinel_run_tool_permissions permissions
             ON permissions.run_id=calls.run_id AND permissions.tool_id=calls.tool_id
             AND permissions.organization_id=calls.organization_id
           WHERE calls.run_id=%s AND calls.organization_id=%s AND calls.status='completed'
             AND permissions.contract_snapshot->>'name'='book_viewing'""", (run_id, organization_id),
    ).fetchall()
    event = connection.execute(
        """SELECT details FROM estate_engagement_events WHERE run_id=%s AND organization_id=%s
           AND event_type='viewing.engagement_recorded'""", (run_id, organization_id),
    ).fetchone()
    draft = connection.execute("SELECT status FROM estate_followup_drafts WHERE run_id=%s AND organization_id=%s", (run_id, organization_id)).fetchone()
    return {
        'completed_bookings': len(calls),
        'property_bound': bool(calls) and all('property_id' in call['arguments'] and 'property_version' in call['arguments'] for call in calls),
        'approvals_consumed': bool(calls) and all(not call['requires_approval'] or call['consumed'] for call in calls),
        'review_required': bool(event and event['details'].get('review_required')),
        'followup_status': draft['status'] if draft else ('blocked' if event else 'not_created'),
    }
