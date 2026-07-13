import { ApiError } from "../api";
import type { SaraHistoryItem, SaraResponse } from "./saraTypes";

export async function sendSaraInteraction(message: string, history: SaraHistoryItem[], sessionId: string | null, route: string): Promise<SaraResponse> {
  const response = await fetch("/api/v1/sara/interactions", {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf(), "Idempotency-Key": `sara.interact:${crypto.randomUUID()}` },
    body: JSON.stringify({ message: message.slice(0, 2000), history: history.slice(-12), session_id: sessionId, route_context: route })
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, response.status === 401 ? "Sessão expirada. Entre novamente." : response.status === 429 ? "Limite de interações atingido. Tente novamente mais tarde." : "SARA indisponível no momento.", response.headers.get("Retry-After"));
  if (!validResponse(data)) throw new Error("Resposta inválida do serviço SARA");
  return data;
}
function csrf(): string { return decodeURIComponent(document.cookie.split("; ").find((v) => v.startsWith("ecos_csrf="))?.split("=")[1] ?? ""); }
function validResponse(value: unknown): value is SaraResponse {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<SaraResponse>;
  return typeof v.response === "string" && v.response.length <= 10000 && typeof v.session_id === "string" && Array.isArray(v.ui_actions) && typeof v.cognitive_state === "string" && typeof v.unavailable === "boolean" && typeof v.incomplete_context === "boolean";
}
