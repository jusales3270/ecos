import type { SaraPoint, SaraPreferences } from "./saraTypes";

const defaults: SaraPreferences = { mode: "closed", position: { x: 24, y: 24 }, voice: true, expansionAllowed: true };
export const saraStorageKey = (organizationId: string, userId: string) => `ecos:sara:v1:${organizationId}:${userId}`;

export function loadSaraPreferences(organizationId: string, userId: string): SaraPreferences {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(saraStorageKey(organizationId, userId)) ?? "null");
    if (!value || typeof value !== "object") return defaults;
    const item = value as Partial<SaraPreferences>;
    const mode = item.mode === "full" || item.mode === "mini" || item.mode === "closed" ? item.mode : defaults.mode;
    return {
      mode, voice: typeof item.voice === "boolean" ? item.voice : true,
      expansionAllowed: typeof item.expansionAllowed === "boolean" ? item.expansionAllowed : true,
      position: validPoint(item.position) ? item.position : defaults.position
    };
  } catch { return defaults; }
}
export function saveSaraPreferences(organizationId: string, userId: string, value: SaraPreferences): void {
  localStorage.setItem(saraStorageKey(organizationId, userId), JSON.stringify(value));
}
function validPoint(value: unknown): value is SaraPoint {
  return Boolean(value && typeof value === "object" && Number.isFinite((value as SaraPoint).x) && Number.isFinite((value as SaraPoint).y));
}
