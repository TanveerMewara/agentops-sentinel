from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import JsonValue

from .booking_adapter import BookingAdapter
from .adapters import AdapterRegistry
from .calendar import NativeCalendar, SlotOffer, CalendarAdapter, RESERVE_CONTRACT, CANCEL_CONTRACT
from .calendar_desk import CalendarProposal, configure as configure_calendar_desk, propose as propose_calendar_action, queue as calendar_action_queue, close as close_calendar_run
from .calendar_workflow import configure as configure_calendar_workflow
from .config import Settings
from .database import Database
from .external_traces import ExternalTraceCreate, ingest_trace, read_trace
from .integrations.otlp_trace import OTLPTraceCreate
from .otlp_receiver import OTLPFinalizeCreate, finalize_otlp, receive_otlp
from .telemetry import (
    RateCardCreate, TelemetryPolicyUpdate, create_rate_card, decode_otlp,
    delete_run_telemetry, get_policy, ingest_signal, list_rate_cards, otlp_success,
    purge_expired, set_policy, telemetry_summary,
)
from .access import KeyCreate, identity, list_keys, create_key, revoke_key, access_events
from .evaluations import (
    DatasetCreate, ExperimentCreate, create_dataset, create_experiment,
    list_datasets, list_experiments, compare_experiments,
)
from .advanced_evaluations import (
    CalibrationCreate, ExperimentAnalysisCreate, HumanLabelCreate, ReleaseGateCreate,
    SamplingPolicyUpdate, analyze_experiments, create_calibration,
    create_human_label, create_release_gate, get_sampling_policy, list_calibrations,
    list_human_labels, list_release_gates, sample_run, set_sampling_policy,
)
from .semantic_judge import OpenAISemanticJudge
from .sessions import (
    InvitationAccept, InvitationCreate, LoginCreate, OrganizationProfileUpdate,
    accept_invitation, configure_organization, create_invitation, list_members,
    login, logout,
)
from .product_operations import (
    AlertPolicyUpdate, DeploymentCreate, DeploymentStatusUpdate, EnvironmentCreate,
    LabCampaignComplete, LabCampaignCreate, acknowledge_alert, claim_campaign,
    complete_campaign, create_campaign, create_deployment, create_environment,
    evaluate_alerts, get_alert_policy, list_alerts, list_campaigns, list_deployments,
    list_environments, set_alert_policy, update_deployment,
)
from .observability import run_timeline, run_summaries
from .operations_overview import operations_overview
from .embeddings import EmbeddingService
from .enquiries import create_lead_run, ingest_delivery
from .engagement import (
    approve_followup_draft, edit_followup_draft, run_engagement_outcomes,
    list_crm_contacts, list_followup_drafts,
)
from .leads import (
    get_lead, list_lead_events, list_lead_versions, list_leads,
    request_handoff, resolve_review, upsert_lead,
)
from .model_gateway import ModelGateway
from .provider_registry import (
    CredentialCipher, configure_openai_provider, list_model_invocations,
    list_model_providers,
)
from .properties import (
    get_property, get_retrieval, list_properties, list_property_versions,
    search_properties, upsert_property, upsert_property_batch,
)
from .repository import create_operation, get_operation, operation_view
from .registry import (
    create_agent, create_tool, grant_tool, list_agent_tools, list_agents,
    list_registry_events, list_tools,
)
from .schemas import (
    AgentCreate, AgentToolGrantCreate, AgentToolGrantView, AgentVersionCreate,
    AgentVersionView, AgentView,
    ApprovalCreate, ApprovalView, EventView, OperationCreate, OperationView,
    EnquiryDeliveryCreate, EnquiryDeliveryView, LeadRunCreate,
    CRMContactView, FollowupDraftView, FollowupDraftEdit, FollowupDraftApprove,
    LeadEventView, LeadHandoffRequest,
    LeadReviewResolve, LeadUpsert,
    LeadUpsertOutcome, LeadVersionView, LeadView,
    ModelInvocationView, ModelProviderView, OpenAIProviderCreate, PropertyBatchUpsert,
    PropertyEmbeddingBackfill, PropertyEmbeddingBackfillView,
    PropertyRetrievalView, PropertySearch, PropertySearchResponse, PropertyUpsert,
    PropertyUpsertOutcome, PropertyVersionView, PropertyView, RegistryEventView,
    RunCreate, RunEventView, RunView, ToolCallApprovalView,
    ToolCallReserve, ToolCallView, ToolCreate, ToolView, WorkflowView,
)
from .security import Principal, authenticate, require_roles
from .http_security import ExternalTraceBodyLimit, ResponseSecurity, validation_error_response
from .service import approve, execute, reconcile, reject, revoke
from .workflow import resume_workflow, start_workflow
from .runs import (
    approve_tool_call, create_agent_version, create_run, execute_registered_tool,
    finish_run, list_agent_versions, list_organization_tool_calls, list_run_events,
    list_runs, list_tool_calls,
    read_run, reconcile_registered_tool, reject_tool_call, reserve_tool_call,
    revoke_tool_call_approval,
)


def create_app(settings: Settings, *, adapters: AdapterRegistry | None = None,
               semantic_judge=None) -> FastAPI:
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.migrate()
        with PostgresSaver.from_conn_string(settings.database_url) as checkpointer:
            checkpointer.setup()
            app.state.workflow_checkpointer = checkpointer
            try:
                yield
            finally:
                database.close()

    app = FastAPI(title="AgentOps Sentinel", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_error_response)
    app.add_middleware(ExternalTraceBodyLimit)
    app.add_middleware(ResponseSecurity)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key", "X-Sentinel-Run-Id",
                       "X-Sentinel-Trace-Id", "X-Sentinel-Source", "X-CSRF-Token"],
    )
    app.state.settings = settings
    app.state.database = database
    app.state.booking_adapter = BookingAdapter(settings.booking_service_url)
    app.state.calendar = NativeCalendar(database)
    app.state.tool_adapters = adapters if adapters is not None else AdapterRegistry(app.state.booking_adapter)
    if adapters is None:
        app.state.tool_adapters.install(RESERVE_CONTRACT, CalendarAdapter(app.state.calendar, "reserve"))
        app.state.tool_adapters.install(CANCEL_CONTRACT, CalendarAdapter(app.state.calendar, "cancel"))
    app.state.credential_cipher = CredentialCipher(settings.credential_encryption_key)
    app.state.semantic_judge = semantic_judge or OpenAISemanticJudge(
        database,app.state.credential_cipher,settings.model_timeout_seconds)
    app.state.model_gateway = ModelGateway(
        database=database,
        cipher=app.state.credential_cipher,
        timeout_seconds=settings.model_timeout_seconds,
    )
    app.state.embedding_service = EmbeddingService(
        database, app.state.credential_cipher,
        timeout_seconds=settings.model_timeout_seconds,
    )

    @app.get("/health")
    def health():
        with database.connect() as connection:
            connection.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/v1/me")
    def current_identity(principal: Principal = Depends(authenticate)):
        return identity(database, principal)

    @app.put('/v1/onboarding/organization')
    def update_organization_profile(body: OrganizationProfileUpdate,
                                    principal: Principal=Depends(authenticate)):
        return configure_organization(database,principal,body)

    @app.post('/v1/onboarding/invitations',status_code=201)
    def invite_organization_member(body: InvitationCreate,
                                   principal: Principal=Depends(authenticate)):
        return create_invitation(database,settings.auth_pepper,principal,body)

    @app.post('/v1/onboarding/accept',status_code=201)
    def accept_member_invitation(body: InvitationAccept,request: Request,response: Response):
        return accept_invitation(database,settings.auth_pepper,request,response,body)

    @app.post('/v1/sessions/login')
    def create_member_session(body: LoginCreate,request: Request,response: Response):
        return login(database,settings.auth_pepper,request,response,body)

    @app.post('/v1/sessions/logout')
    def close_member_session(request: Request,response: Response,
                             principal: Principal=Depends(authenticate)):
        return logout(database,settings.auth_pepper,request,response)

    @app.get('/v1/onboarding/members')
    def organization_members(principal: Principal=Depends(authenticate)):
        return list_members(database,principal)

    @app.get('/v1/alerts/policy')
    def read_alert_policy(principal: Principal=Depends(authenticate)):
        return get_alert_policy(database,principal)

    @app.put('/v1/alerts/policy')
    def update_alert_policy(body: AlertPolicyUpdate,
                            principal: Principal=Depends(authenticate)):
        return set_alert_policy(database,principal,body)

    @app.post('/v1/alerts/evaluate')
    def run_alert_evaluation(principal: Principal=Depends(authenticate)):
        return evaluate_alerts(database,principal)

    @app.get('/v1/alerts')
    def operational_alerts(alert_status: str | None=Query(default=None,alias='status',pattern='^(open|acknowledged|resolved)$'),
                           principal: Principal=Depends(authenticate)):
        return list_alerts(database,principal,alert_status)

    @app.post('/v1/alerts/{alert_id}/acknowledge')
    def acknowledge_operational_alert(alert_id: UUID,
                                      principal: Principal=Depends(authenticate)):
        return acknowledge_alert(database,principal,alert_id)

    @app.post('/v1/deployments/environments',status_code=201)
    def register_deployment_environment(body: EnvironmentCreate,
                                        principal: Principal=Depends(authenticate)):
        return create_environment(database,principal,body)

    @app.get('/v1/deployments/environments')
    def deployment_environments(principal: Principal=Depends(authenticate)):
        return list_environments(database,principal)

    @app.post('/v1/deployments',status_code=201)
    def approve_deployment(body: DeploymentCreate,
                           principal: Principal=Depends(authenticate)):
        return create_deployment(database,principal,body)

    @app.get('/v1/deployments')
    def deployments(principal: Principal=Depends(authenticate)):
        return list_deployments(database,principal)

    @app.post('/v1/deployments/{deployment_id}/status')
    def change_deployment_status(deployment_id: UUID,body: DeploymentStatusUpdate,
                                 principal: Principal=Depends(authenticate)):
        return update_deployment(database,principal,deployment_id,body)

    @app.post('/v1/labs/campaigns',status_code=201)
    def schedule_lab_campaign(body: LabCampaignCreate,
                              principal: Principal=Depends(authenticate)):
        return create_campaign(database,principal,body)

    @app.get('/v1/labs/campaigns')
    def lab_campaigns(principal: Principal=Depends(authenticate)):
        return list_campaigns(database,principal)

    @app.post('/v1/labs/campaigns/claim')
    def claim_lab_campaign(principal: Principal=Depends(authenticate)):
        return claim_campaign(database,principal)

    @app.post('/v1/labs/campaigns/{campaign_id}/complete')
    def finish_lab_campaign(campaign_id: UUID,body: LabCampaignComplete,
                            principal: Principal=Depends(authenticate)):
        return complete_campaign(database,principal,campaign_id,body)

    @app.get("/v1/run-summaries")
    def redacted_run_summaries(limit: int = Query(default=20, ge=1, le=100),
                              principal: Principal = Depends(authenticate)):
        return run_summaries(database, principal, limit)

    @app.get("/v1/operations/overview")
    def operational_counters(principal: Principal = Depends(authenticate)):
        return operations_overview(database, principal, settings, app.state.tool_adapters)

    @app.post("/v1/calendar/configuration")
    def calendar_configuration(principal: Principal = Depends(authenticate)):
        return configure_calendar_desk(database, principal, app.state.tool_adapters)

    @app.post("/v1/calendar/workflow/configuration")
    def calendar_workflow_configuration(principal: Principal = Depends(authenticate)):
        return configure_calendar_workflow(database, principal, app.state.tool_adapters)

    @app.post("/v1/calendar/proposals", response_model=ToolCallView)
    def calendar_proposal(body: CalendarProposal, principal: Principal = Depends(authenticate)):
        return propose_calendar_action(database, principal, app.state.tool_adapters, body)

    @app.post("/v1/calendar/actions/{tool_call_id}/close", response_model=RunView)
    def close_calendar_action_run(tool_call_id: UUID, principal: Principal = Depends(authenticate)):
        return close_calendar_run(database, principal, tool_call_id)

    @app.get("/v1/calendar/actions")
    def calendar_actions(limit: int = Query(default=50, ge=1, le=100), principal: Principal = Depends(authenticate)):
        return calendar_action_queue(database, principal, app.state.tool_adapters, limit)

    @app.post("/v1/calendar/slots")
    def offer_calendar_slot(body: SlotOffer, principal: Principal = Depends(authenticate)):
        return app.state.calendar.offer(principal, body)

    @app.get("/v1/calendar/slots")
    def available_calendar_slots(limit: int = Query(default=50, ge=1, le=100),
                                 principal: Principal = Depends(authenticate)):
        return app.state.calendar.slots(principal, limit)

    @app.post("/v1/calendar/slots/{slot_id}/withdraw")
    def withdraw_calendar_slot(slot_id: UUID, principal: Principal = Depends(authenticate)):
        return app.state.calendar.withdraw(principal, slot_id)

    @app.get("/v1/calendar/reservations")
    def calendar_reservations(limit: int = Query(default=50, ge=1, le=100),
                              principal: Principal = Depends(authenticate)):
        return app.state.calendar.reservations(principal, limit)

    @app.get("/v1/access/keys")
    def organization_keys(principal: Principal = Depends(authenticate)):
        return list_keys(database, principal)

    @app.post("/v1/access/keys", status_code=201)
    def issue_api_key(body: KeyCreate, response: Response,
                      principal: Principal = Depends(authenticate)):
        response.headers["Cache-Control"] = "no-store"
        return create_key(database, settings.auth_pepper, principal, body)

    @app.post("/v1/access/keys/{key_id}/revoke")
    def revoke_api_key(key_id: UUID, principal: Principal = Depends(authenticate)):
        return revoke_key(database, principal, key_id)

    @app.get("/v1/access/events")
    def key_audit_events(limit: int = Query(default=50, ge=1, le=100),
                          principal: Principal = Depends(authenticate)):
        return access_events(database, principal, limit)

    @app.post("/v1/evaluations/datasets")
    def register_evaluation_dataset(body: DatasetCreate, response: Response,
                                    principal: Principal = Depends(authenticate)):
        result, created = create_dataset(database, principal, body)
        response.status_code = 201 if created else 200
        return result

    @app.get("/v1/evaluations/datasets")
    def evaluation_datasets(limit: int = Query(default=50, ge=1, le=100),
                            principal: Principal = Depends(authenticate)):
        return list_datasets(database, principal, limit)

    @app.post("/v1/evaluations/experiments")
    def evaluate_saved_runs(body: ExperimentCreate, response: Response,
                           principal: Principal = Depends(authenticate)):
        result, created = create_experiment(database, principal, body, app.state.semantic_judge)
        response.status_code = 201 if created else 200
        return result

    @app.get("/v1/evaluations/experiments")
    def evaluation_experiments(limit: int = Query(default=50, ge=1, le=100),
                               principal: Principal = Depends(authenticate)):
        return list_experiments(database, principal, limit)

    @app.get("/v1/evaluations/compare")
    def evaluation_comparison(left: UUID, right: UUID,
                              principal: Principal = Depends(authenticate)):
        return compare_experiments(database, principal, left, right)

    @app.post('/v1/evaluations/human-labels')
    def add_human_label(body: HumanLabelCreate,response: Response,
                        principal: Principal=Depends(authenticate)):
        result,created=create_human_label(database,principal,body)
        response.status_code=201 if created else 200
        return result

    @app.get('/v1/evaluations/human-labels')
    def evaluation_human_labels(dataset_id: UUID,
                                principal: Principal=Depends(authenticate)):
        return list_human_labels(database,principal,dataset_id)

    @app.post('/v1/evaluations/calibrations')
    def calibrate_semantic_judge(body: CalibrationCreate,response: Response,
                                 principal: Principal=Depends(authenticate)):
        result,created=create_calibration(database,principal,body)
        response.status_code=201 if created else 200
        return result

    @app.get('/v1/evaluations/calibrations')
    def evaluation_calibrations(principal: Principal=Depends(authenticate)):
        return list_calibrations(database,principal)

    @app.post('/v1/evaluations/analysis')
    def analyze_evaluation_repetitions(body: ExperimentAnalysisCreate,
                                       principal: Principal=Depends(authenticate)):
        return analyze_experiments(database,principal,body)

    @app.post('/v1/evaluations/release-gates')
    def evaluate_release_gate(body: ReleaseGateCreate,response: Response,
                              principal: Principal=Depends(authenticate)):
        result,created=create_release_gate(database,principal,body)
        response.status_code=201 if created else 200
        return result

    @app.get('/v1/evaluations/release-gates')
    def evaluation_release_gates(principal: Principal=Depends(authenticate)):
        return list_release_gates(database,principal)

    @app.put('/v1/evaluations/online-policy')
    def update_online_evaluation_policy(body: SamplingPolicyUpdate,
                                        principal: Principal=Depends(authenticate)):
        return set_sampling_policy(database,principal,body)

    @app.get('/v1/evaluations/online-policy')
    def read_online_evaluation_policy(principal: Principal=Depends(authenticate)):
        return get_sampling_policy(database,principal)

    @app.post('/v1/runs/{run_id}/evaluation-sample')
    def evaluate_online_sample(run_id: UUID,principal: Principal=Depends(authenticate)):
        return sample_run(database,principal,run_id,app.state.semantic_judge)

    @app.post("/v1/runs/{run_id}/external-trace")
    def record_external_trace(run_id: UUID, body: ExternalTraceCreate, response: Response,
                              principal: Principal = Depends(authenticate)):
        result, created = ingest_trace(database, principal, run_id, body)
        response.status_code = 201 if created else 200
        return result

    @app.post("/v1/runs/{run_id}/external-trace/otlp")
    def record_otlp_external_trace(run_id: UUID, body: OTLPTraceCreate, response: Response,
                                   principal: Principal = Depends(authenticate)):
        try:
            evidence = ExternalTraceCreate.model_validate(body.evidence())
        except (ValueError, RecursionError):
            raise HTTPException(422, "OTLP trace validation failed.") from None
        result, created = ingest_trace(database, principal, run_id, evidence)
        response.status_code = 201 if created else 200
        return result

    async def receive_standard_otlp(signal: str, request: Request, run_id: UUID,
                                    trace_id: str | None, source: str,
                                    principal: Principal):
        message, payload, decoded, media_type = decode_otlp(
            signal, await request.body(), request.headers.get('content-type'),
            request.headers.get('content-encoding'))
        try:
            if signal == 'traces':
                receive_otlp(database, principal, run_id, payload,
                             trace_id=trace_id, source=source)
            else:
                ingest_signal(database, principal, run_id, signal, payload, decoded)
        except (ValueError, RecursionError):
            raise HTTPException(422, f'OTLP {signal} validation failed.') from None
        content, response_type = otlp_success(signal, media_type)
        return Response(content=content, status_code=200,
                        headers={'Content-Type': response_type})

    @app.post("/v1/traces")
    async def receive_otlp_trace(request: Request,
                           x_sentinel_run_id: UUID = Header(alias='X-Sentinel-Run-Id'),
                           x_sentinel_trace_id: str | None = Header(default=None, alias='X-Sentinel-Trace-Id'),
                           x_sentinel_source: str = Header(default='opentelemetry', alias='X-Sentinel-Source'),
                           principal: Principal = Depends(authenticate)):
        return await receive_standard_otlp('traces', request, x_sentinel_run_id,
                                           x_sentinel_trace_id, x_sentinel_source, principal)

    @app.post("/v1/metrics")
    async def receive_otlp_metrics(request: Request,
                            x_sentinel_run_id: UUID = Header(alias='X-Sentinel-Run-Id'),
                            principal: Principal = Depends(authenticate)):
        return await receive_standard_otlp('metrics', request, x_sentinel_run_id,
                                           None, 'opentelemetry', principal)

    @app.post("/v1/logs")
    async def receive_otlp_logs(request: Request,
                         x_sentinel_run_id: UUID = Header(alias='X-Sentinel-Run-Id'),
                         principal: Principal = Depends(authenticate)):
        return await receive_standard_otlp('logs', request, x_sentinel_run_id,
                                           None, 'opentelemetry', principal)

    @app.get("/v1/telemetry/policy")
    def read_telemetry_policy(principal: Principal = Depends(authenticate)):
        return get_policy(database, principal)

    @app.put("/v1/telemetry/policy")
    def update_telemetry_policy(body: TelemetryPolicyUpdate,
                                principal: Principal = Depends(authenticate)):
        return set_policy(database, principal, body)

    @app.post("/v1/telemetry/rate-cards", status_code=201)
    def add_telemetry_rate_card(body: RateCardCreate,
                                principal: Principal = Depends(authenticate)):
        return create_rate_card(database, principal, body)

    @app.get("/v1/telemetry/rate-cards")
    def read_telemetry_rate_cards(principal: Principal = Depends(authenticate)):
        return list_rate_cards(database, principal)

    @app.post("/v1/telemetry/retention/purge")
    def purge_telemetry(principal: Principal = Depends(authenticate)):
        return purge_expired(database, principal)

    @app.get("/v1/runs/{run_id}/telemetry")
    def read_run_telemetry(run_id: UUID, principal: Principal = Depends(authenticate)):
        return telemetry_summary(database, principal, run_id)

    @app.delete("/v1/runs/{run_id}/telemetry")
    def remove_run_telemetry(run_id: UUID, principal: Principal = Depends(authenticate)):
        return delete_run_telemetry(database, principal, run_id)

    @app.post("/v1/runs/{run_id}/external-trace/otlp/finalize")
    def finalize_otlp_trace(run_id: UUID, body: OTLPFinalizeCreate, response: Response,
                            principal: Principal = Depends(authenticate)):
        try:
            evidence = finalize_otlp(database, principal, run_id, body)
        except (ValueError, RecursionError):
            raise HTTPException(422, 'OTLP finalization validation failed.') from None
        result, created = ingest_trace(database, principal, run_id, evidence)
        response.status_code = 201 if created else 200
        return result

    @app.get("/v1/runs/{run_id}/external-trace")
    def external_trace(run_id: UUID, include_output: bool = False,
                       principal: Principal = Depends(authenticate)):
        return read_trace(database, principal, run_id, include_output)

    @app.get("/v1/runs/{run_id}/timeline")
    def execution_timeline(run_id: UUID, principal: Principal = Depends(authenticate)):
        return run_timeline(database, principal, str(run_id))

    @app.post("/v1/agents", response_model=AgentView)
    def register_agent(body: AgentCreate, response: Response,
                       principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        result, created = create_agent(database, principal, body)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/agents", response_model=list[AgentView])
    def registered_agents(principal: Principal = Depends(authenticate)):
        return list_agents(database, principal)

    @app.post("/v1/tools", response_model=ToolView)
    def register_tool(body: ToolCreate, response: Response,
                      principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        result, created = create_tool(database, principal, body)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/tools", response_model=list[ToolView])
    def registered_tools(principal: Principal = Depends(authenticate)):
        return list_tools(database, principal)

    @app.post(
        "/v1/agents/{agent_id}/tools/{tool_id}",
        response_model=AgentToolGrantView,
    )
    def authorize_agent_tool(agent_id: str, tool_id: str, body: AgentToolGrantCreate,
                             principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        return grant_tool(database, principal, agent_id, tool_id, body)

    @app.get(
        "/v1/agents/{agent_id}/tools",
        response_model=list[AgentToolGrantView],
    )
    def agent_tools(agent_id: str, principal: Principal = Depends(authenticate)):
        return list_agent_tools(database, principal, agent_id)

    @app.get("/v1/registry/events", response_model=list[RegistryEventView])
    def registry_events(
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal = Depends(authenticate),
    ):
        return list_registry_events(database, principal, limit)

    @app.post("/v1/model-providers/openai", response_model=ModelProviderView)
    def configure_openai(body: OpenAIProviderCreate, response: Response,
                         principal: Principal = Depends(authenticate)):
        require_roles("admin")(principal)
        result, created = configure_openai_provider(
            database, app.state.credential_cipher, principal, body
        )
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/model-providers", response_model=list[ModelProviderView])
    def model_providers(principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        return list_model_providers(database, principal)

    @app.post("/v1/leads", response_model=LeadUpsertOutcome)
    def ingest_lead(body: LeadUpsert, response: Response,
                    principal: Principal = Depends(authenticate)):
        lead, outcome = upsert_lead(
            database, app.state.credential_cipher, principal, body
        )
        response.status_code = (
            status.HTTP_201_CREATED if outcome == "created" else status.HTTP_200_OK
        )
        return {"lead": lead, "outcome": outcome}

    @app.post("/v1/enquiries/website", response_model=EnquiryDeliveryView)
    def website_enquiry(body: EnquiryDeliveryCreate, response: Response,
                         principal: Principal = Depends(authenticate)):
        receipt, created = ingest_delivery(
            database, app.state.credential_cipher, principal, body
        )
        response.status_code = 201 if created else 200
        return receipt

    @app.post("/v1/leads/{lead_id}/runs", response_model=RunView)
    def launch_lead_run(lead_id: UUID, body: LeadRunCreate, response: Response,
                        principal: Principal = Depends(authenticate)):
        run, created = create_lead_run(database, principal, str(lead_id), body)
        response.status_code = 201 if created else 200
        return run

    @app.get("/v1/workflows/actionable", response_model=list[RunView])
    def actionable_workflows(
        limit: int = Query(default=25, ge=1, le=100),
        principal: Principal = Depends(authenticate),
    ):
        require_roles("admin", "worker")(principal)
        from .runs import run_view
        with database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM sentinel_runs runs WHERE organization_id=%s
                     AND status IN ('queued', 'running')
                     AND input_payload->>'workflow'='estateflow'
                     AND NOT EXISTS (
                       SELECT 1 FROM sentinel_tool_calls calls
                       WHERE calls.run_id=runs.run_id
                         AND calls.organization_id=runs.organization_id
                         AND calls.status='awaiting_approval')
                   ORDER BY (status='queued') DESC, created_at, run_id LIMIT %s""",
                (principal.organization_id, limit),
            ).fetchall()
        return [run_view(row) for row in rows]

    @app.get("/v1/leads", response_model=list[LeadView])
    def leads(
        limit: int = Query(default=50, ge=1, le=100),
        qualification_status: Literal[
            "needs_information", "qualified", "nurture", "human_review"
        ] | None = Query(default=None, alias="status"),
        principal: Principal = Depends(authenticate),
    ):
        return list_leads(
            database, app.state.credential_cipher, principal, limit,
            qualification_status,
        )

    @app.get("/v1/leads/{lead_id}", response_model=LeadView)
    def lead_record(lead_id: str,
                    principal: Principal = Depends(authenticate)):
        return get_lead(database, app.state.credential_cipher, principal, lead_id)

    @app.get("/v1/leads/{lead_id}/events", response_model=list[LeadEventView])
    def lead_events(lead_id: str,
                    principal: Principal = Depends(authenticate)):
        return list_lead_events(database, principal, lead_id)

    @app.get("/v1/leads/{lead_id}/versions", response_model=list[LeadVersionView])
    def lead_versions(lead_id: str,
                      principal: Principal = Depends(authenticate)):
        return list_lead_versions(database, principal, lead_id)

    @app.post("/v1/leads/{lead_id}/handoff", response_model=LeadView)
    def lead_handoff(lead_id: str, body: LeadHandoffRequest,
                     principal: Principal = Depends(authenticate)):
        return request_handoff(
            database, app.state.credential_cipher, principal, lead_id, body
        )

    @app.post("/v1/leads/{lead_id}/resolve-review", response_model=LeadView)
    def lead_review_resolution(lead_id: str, body: LeadReviewResolve,
                               principal: Principal = Depends(authenticate)):
        return resolve_review(
            database, app.state.credential_cipher, principal, lead_id, body
        )

    @app.get("/v1/crm/contacts", response_model=list[CRMContactView])
    def crm_contacts(
        limit: int = Query(default=50, ge=1, le=100),
        principal: Principal = Depends(authenticate),
    ):
        return list_crm_contacts(database, principal, limit)

    @app.get("/v1/followups", response_model=list[FollowupDraftView])
    def followup_drafts(
        limit: int = Query(default=50, ge=1, le=100),
        draft_status: Literal["draft", "approved", "cancelled"] | None = Query(
            default=None, alias="status"
        ),
        principal: Principal = Depends(authenticate),
    ):
        return list_followup_drafts(
            database, app.state.credential_cipher, principal, limit, draft_status
        )

    @app.post(
        "/v1/followups/{draft_id}/approve", response_model=FollowupDraftView
    )
    def approve_followup(draft_id: UUID, body: FollowupDraftApprove,
                         principal: Principal = Depends(authenticate)):
        return approve_followup_draft(
            database, app.state.credential_cipher, principal, str(draft_id), body.expected_revision
        )

    @app.patch("/v1/followups/{draft_id}", response_model=FollowupDraftView)
    def edit_followup(draft_id: UUID, body: FollowupDraftEdit,
                      principal: Principal = Depends(authenticate)):
        return edit_followup_draft(database, app.state.credential_cipher, principal, str(draft_id), body)

    @app.get("/v1/runs/{run_id}/engagement")
    def engagement_outcomes(run_id: UUID, principal: Principal = Depends(authenticate)):
        return run_engagement_outcomes(database, principal, str(run_id))

    @app.post("/v1/properties", response_model=PropertyUpsertOutcome)
    def ingest_property(body: PropertyUpsert, response: Response,
                        principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        property_record, outcome = upsert_property(database, principal, body)
        response.status_code = (
            status.HTTP_201_CREATED if outcome == "created" else status.HTTP_200_OK
        )
        return {"property": property_record, "outcome": outcome}

    @app.post("/v1/properties/batch", response_model=list[PropertyUpsertOutcome])
    def ingest_property_batch(body: PropertyBatchUpsert,
                              principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        return upsert_property_batch(database, principal, body.properties)

    @app.get("/v1/properties", response_model=list[PropertyView])
    def properties(
        limit: int = Query(default=50, ge=1, le=100),
        city: str | None = Query(default=None, min_length=1, max_length=100),
        property_type: Literal[
            "apartment", "house", "villa", "plot", "commercial"
        ] | None = None,
        listing_status: Literal["active", "reserved", "sold", "inactive"] | None = None,
        principal: Principal = Depends(authenticate),
    ):
        return list_properties(
            database, principal, limit, city, property_type, listing_status
        )

    @app.post("/v1/properties/search", response_model=PropertySearchResponse)
    def property_search(body: PropertySearch,
                        principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer", "worker")(principal)
        return search_properties(
            database, principal, body,
            embedding_service=app.state.embedding_service,
        )

    @app.post(
        "/v1/properties/embeddings/backfill",
        response_model=PropertyEmbeddingBackfillView,
    )
    def backfill_property_embeddings(
        body: PropertyEmbeddingBackfill,
        principal: Principal = Depends(authenticate),
    ):
        require_roles("admin")(principal)
        return app.state.embedding_service.backfill(principal, body)

    @app.get("/v1/properties/{property_id}", response_model=PropertyView)
    def property_record(property_id: str,
                        principal: Principal = Depends(authenticate)):
        return get_property(database, principal, property_id)

    @app.get(
        "/v1/properties/{property_id}/versions",
        response_model=list[PropertyVersionView],
    )
    def property_versions(property_id: str,
                          principal: Principal = Depends(authenticate)):
        return list_property_versions(database, principal, property_id)

    @app.get(
        "/v1/property-searches/{retrieval_id}",
        response_model=PropertyRetrievalView,
    )
    def property_retrieval(retrieval_id: str,
                           principal: Principal = Depends(authenticate)):
        return get_retrieval(database, principal, retrieval_id)

    @app.post("/v1/agents/{agent_id}/versions", response_model=AgentVersionView)
    def register_agent_version(agent_id: str, body: AgentVersionCreate, response: Response,
                               principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        result, created = create_agent_version(database, principal, agent_id, body)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/agents/{agent_id}/versions", response_model=list[AgentVersionView])
    def agent_versions(agent_id: str, principal: Principal = Depends(authenticate)):
        return list_agent_versions(database, principal, agent_id)

    @app.post("/v1/runs", response_model=RunView)
    def start_run(body: RunCreate, response: Response,
                  principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        result, created = create_run(database, principal, body)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/runs", response_model=list[RunView])
    def runs(
        limit: int = Query(default=50, ge=1, le=100),
        run_status: Literal[
            "queued", "running", "succeeded", "failed", "cancelled", "needs_review"
        ] | None = Query(default=None, alias="status"),
        principal: Principal = Depends(authenticate),
    ):
        return list_runs(database, principal, limit, run_status)

    @app.get("/v1/runs/{run_id}", response_model=RunView)
    def run(run_id: str, principal: Principal = Depends(authenticate)):
        return read_run(database, principal, run_id)

    @app.post("/v1/runs/{run_id}/tool-calls", response_model=ToolCallView)
    def reserve_call(run_id: str, body: ToolCallReserve, response: Response,
                     principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        result, created = reserve_tool_call(database, principal, run_id, body)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/runs/{run_id}/tool-calls", response_model=list[ToolCallView])
    def run_tool_calls(run_id: str, principal: Principal = Depends(authenticate)):
        return list_tool_calls(database, principal, run_id)

    @app.get("/v1/tool-calls", response_model=list[ToolCallView])
    def actionable_tool_calls(
        call_status: Literal["authorized", "executing", "unknown"] = Query(alias="status"),
        limit: int = Query(default=25, ge=1, le=100),
        principal: Principal = Depends(authenticate),
    ):
        require_roles("admin", "worker")(principal)
        return list_organization_tool_calls(database, principal, call_status, limit, app.state.tool_adapters)

    @app.post(
        "/v1/runs/{run_id}/tool-calls/{tool_call_id}/approve",
        response_model=ToolCallApprovalView,
    )
    def approve_call(run_id: str, tool_call_id: str, body: ApprovalCreate,
                     principal: Principal = Depends(authenticate)):
        require_roles("admin", "reviewer")(principal)
        return approve_tool_call(
            database, principal, run_id, tool_call_id, body.valid_for_seconds
        )

    @app.post(
        "/v1/runs/{run_id}/tool-calls/{tool_call_id}/reject",
        response_model=ToolCallView,
    )
    def reject_call(run_id: str, tool_call_id: str,
                    principal: Principal = Depends(authenticate)):
        require_roles("admin", "reviewer")(principal)
        return reject_tool_call(database, principal, run_id, tool_call_id)

    @app.post(
        "/v1/runs/{run_id}/tool-calls/{tool_call_id}/revoke",
        response_model=ToolCallView,
    )
    def revoke_call(run_id: str, tool_call_id: str,
                    principal: Principal = Depends(authenticate)):
        require_roles("admin", "reviewer")(principal)
        return revoke_tool_call_approval(database, principal, run_id, tool_call_id)

    @app.post(
        "/v1/runs/{run_id}/tool-calls/{tool_call_id}/execute",
        response_model=ToolCallView,
    )
    def execute_call(run_id: str, tool_call_id: str,
                     principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return execute_registered_tool(
            database, principal, run_id, tool_call_id, app.state.tool_adapters,
            settings.execution_lease_seconds,
        )

    @app.post(
        "/v1/runs/{run_id}/tool-calls/{tool_call_id}/reconcile",
        response_model=ToolCallView,
    )
    def reconcile_call(run_id: str, tool_call_id: str,
                       principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return reconcile_registered_tool(
            database, principal, run_id, tool_call_id, app.state.tool_adapters,
            settings.execution_lease_seconds,
        )

    @app.post("/v1/runs/{run_id}/complete", response_model=RunView)
    def complete_run(run_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return finish_run(database, principal, run_id)

    @app.get("/v1/runs/{run_id}/events", response_model=list[RunEventView])
    def run_events(run_id: str, principal: Principal = Depends(authenticate)):
        return list_run_events(database, principal, run_id)

    @app.get(
        "/v1/runs/{run_id}/model-invocations",
        response_model=list[ModelInvocationView],
    )
    def model_invocations(run_id: str, principal: Principal = Depends(authenticate)):
        return list_model_invocations(database, principal, run_id)

    @app.post("/v1/runs/{run_id}/workflow/start", response_model=WorkflowView)
    def begin_workflow(run_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return start_workflow(
            database, principal, run_id, app.state.model_gateway,
            app.state.tool_adapters, settings.execution_lease_seconds,
            app.state.workflow_checkpointer,
        )

    @app.post("/v1/runs/{run_id}/workflow/resume", response_model=WorkflowView)
    def continue_workflow(run_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return resume_workflow(
            database, principal, run_id, app.state.model_gateway,
            app.state.tool_adapters, settings.execution_lease_seconds,
            app.state.workflow_checkpointer,
        )

    @app.post("/v1/operations", response_model=OperationView)
    def create(body: OperationCreate, response: Response,
               principal: Principal = Depends(authenticate)):
        require_roles("admin", "developer")(principal)
        result, created = create_operation(database, principal, body)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @app.get("/v1/operations/{operation_id}", response_model=OperationView)
    def read(operation_id: str, principal: Principal = Depends(authenticate)):
        with database.connect() as connection:
            return operation_view(get_operation(connection, principal.organization_id, operation_id))

    @app.get("/v1/operations", response_model=list[OperationView])
    def list_operations(
                        limit: int = Query(default=50, ge=1, le=100),
                        operation_status: Literal[
                            "awaiting_approval", "authorized", "executing", "unknown",
                            "succeeded", "failed", "needs_review", "rejected"
                        ] | None = Query(default=None, alias="status"),
                        principal: Principal = Depends(authenticate)):
        with database.connect() as connection:
            if operation_status is None:
                rows = connection.execute(
                    """SELECT * FROM sentinel_operations
                       WHERE organization_id=%s
                       ORDER BY created_at DESC, operation_id DESC LIMIT %s""",
                    (principal.organization_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM sentinel_operations
                       WHERE organization_id=%s AND status=%s
                       ORDER BY created_at DESC, operation_id DESC LIMIT %s""",
                    (principal.organization_id, operation_status, limit),
                ).fetchall()
        return [operation_view(row) for row in rows]

    @app.get("/v1/operations/{operation_id}/events", response_model=list[EventView])
    def events(operation_id: str, principal: Principal = Depends(authenticate)):
        with database.connect() as connection:
            operation = get_operation(connection, principal.organization_id, operation_id)
            return connection.execute(
                """SELECT event_id, event_type, from_status, to_status, details, created_at
                   FROM sentinel_operation_events WHERE operation_id=%s ORDER BY event_id""",
                (operation["operation_id"],),
            ).fetchall()

    @app.post("/v1/operations/{operation_id}/approve", response_model=ApprovalView)
    def grant(operation_id: str, body: ApprovalCreate,
              principal: Principal = Depends(authenticate)):
        require_roles("admin", "reviewer")(principal)
        return approve(database, principal, operation_id, body.valid_for_seconds)

    @app.post("/v1/operations/{operation_id}/reject", response_model=OperationView)
    def decline(operation_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "reviewer")(principal)
        return reject(database, principal, operation_id)

    @app.post("/v1/operations/{operation_id}/revoke", response_model=OperationView)
    def withdraw(operation_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "reviewer")(principal)
        return revoke(database, principal, operation_id)

    @app.post("/v1/operations/{operation_id}/execute", response_model=OperationView)
    def dispatch(operation_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return execute(
            database, principal, operation_id, app.state.booking_adapter,
            settings.execution_lease_seconds,
        )

    @app.post("/v1/operations/{operation_id}/reconcile", response_model=OperationView)
    def investigate(operation_id: str, principal: Principal = Depends(authenticate)):
        require_roles("admin", "worker")(principal)
        return reconcile(
            database, principal, operation_id, app.state.booking_adapter,
            settings.execution_lease_seconds,
        )

    return app
