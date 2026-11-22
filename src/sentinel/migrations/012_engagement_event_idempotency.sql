ALTER TABLE estate_engagement_events
    ADD CONSTRAINT estate_engagement_events_run_type_key
    UNIQUE (run_id, event_type);
