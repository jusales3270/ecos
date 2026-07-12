export type Principal = {
  user_id: string;
  organization_id: string;
  roles: string[];
  permissions: string[];
  authentication_method: string;
  session_id: string | null;
  token_id: string | null;
  issued_at: string;
  expires_at: string;
  correlation_id: string;
};

export type AuthState = {
  principal: Principal;
  organization: { organization_id: string; name: string };
  demo: boolean;
};

export type TimelineEntry = {
  sequence: number;
  event_type: string;
  message: string;
  occurred_at: string;
  actor_id: string | null;
  correlation_id: string;
};

export type Recommendation = {
  recommendation_id: string;
  session_id: string;
  summary: string;
  confidence: number;
  risks: string[];
  evidence: string[];
  plan: string[];
  reasoning: string | null;
  debate: string | null;
  simulation: string | null;
  decision: string | null;
  created_at: string;
};

export type Approval = {
  approval_id: string;
  organization_id: string;
  session_id: string;
  recommendation_id: string;
  requester_id: string;
  requester_email: string;
  status: "pending" | "approved" | "rejected";
  risks: string[];
  plan: string[];
  required_independent_approver: boolean;
  decided_by: string | null;
  decided_by_email: string | null;
  decided_at: string | null;
  rejection_reason: string | null;
  correlation_id: string;
  created_at: string;
};

export type Execution = {
  execution_id: string;
  organization_id: string;
  session_id: string;
  approval_id: string | null;
  status: "blocked" | "ready" | "running" | "completed" | "failed";
  approved_plan: string[];
  attempts: number;
  connector_id: string;
  dry_run: boolean;
  result: string | null;
  error: string | null;
  observations: string[];
  feedback: string[];
  learning: string[];
  history: TimelineEntry[];
  correlation_id: string;
  created_at: string;
  updated_at: string;
};

export type OperationalSession = {
  session_id: string;
  organization_id: string;
  created_by: string;
  created_by_email: string;
  objective: string;
  description: string | null;
  status:
    | "created"
    | "processing"
    | "waiting_approval"
    | "approved"
    | "rejected"
    | "executing"
    | "completed"
    | "failed";
  context: Record<string, unknown>;
  stages: string[];
  recommendation: Recommendation | null;
  approval: Approval | null;
  execution: Execution | null;
  timeline: TimelineEntry[];
  correlation_id: string;
  created_at: string;
  updated_at: string;
};

export type Overview = {
  organization: { organization_id: string; name: string };
  user: { user_id: string; email: string; display_name: string };
  roles: string[];
  permissions: string[];
  recent_sessions: OperationalSession[];
  sessions_by_status: Record<string, number>;
  pending_approvals: number;
  running_executions: number;
  approval_rate: number;
  execution_success_rate: number;
  average_recommendation_confidence: number;
  recent_events: EventRecord[];
  component_health: { component: string; status: string }[];
  observability: Record<string, unknown>;
};

export type EventRecord = {
  sequence: number;
  event_id: string;
  event_type: string;
  category: string;
  source: string;
  session_id: string | null;
  correlation_id: string | null;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export type KnowledgeResult = {
  entity_id: string;
  name: string;
  type: string;
  score: number;
  confidence: number;
  importance: number;
  version: number;
  source: string[];
};

export type VersionInfo = {
  name: string;
  service: string;
  version: string;
  environment: string;
  commit_sha: string;
  build_date: string;
  schema_revision: string;
};

export type ReadinessInfo = {
  ready: boolean;
  schema_revision: string | null;
  components: Record<string, { status: string; [key: string]: unknown }>;
};

export type OutboxMessage = {
  message_id: string;
  event_type: string;
  status: string;
  attempts: number;
  created_at: string;
  delivered_at: string | null;
  last_error: string | null;
};
