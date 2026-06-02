/** Runtime configuration for API and feature flags. */

export const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV ?? "development";

export const ENABLE_MOCK_FALLBACK =
  process.env.NEXT_PUBLIC_ENABLE_MOCK_FALLBACK === "true";

export const USE_API_PROXY =
  process.env.NEXT_PUBLIC_USE_API_PROXY === "true";

const DEFAULT_API = "http://localhost:8000";

/** Resolve API base URL for fetch calls (client or server). */
export function resolveApiBaseUrl(): string {
  if (USE_API_PROXY) {
    return "";
  }
  if (typeof window === "undefined" && process.env.API_INTERNAL_URL?.trim()) {
    return process.env.API_INTERNAL_URL.replace(/\/$/, "");
  }
  return (process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API).replace(/\/$/, "");
}

/** Build full API path with optional same-origin proxy prefix. */
export function apiUrl(path: string): string {
  const base = resolveApiBaseUrl();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (!base) {
    return `/api/proxy${normalized}`;
  }
  return `${base}${normalized}`;
}
