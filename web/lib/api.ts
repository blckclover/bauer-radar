import type { ZodSchema } from "zod";

import type {
  AnalyzeResponse,
  HunterScanRequest,
  HunterScanResponse,
  HunterScanTaskCreated,
  HunterTaskStatus,
  NarrativeResponse,
  NarrativeResult,
  RedTeamFinding,
  ScorecardResult,
  StrategyMode,
  WatchlistEntry,
} from "@/types";
import { apiUrl, ENABLE_MOCK_FALLBACK } from "@/lib/config";
import { isPoisonedNarrative } from "@/lib/format";
import { getMockDashboardData } from "@/lib/mockData";
import {
  hunterScanResponseSchema,
  hunterScanTaskCreatedSchema,
  hunterTaskStatusSchema,
  narrativeResponseSchema,
} from "@/lib/schemas";

const DEFAULT_TIMEOUT_MS = 120_000;

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "api_error") {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

export interface SafeFetchOptions<T> {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  schema?: ZodSchema<T>;
}

function parseApiErrorBody(body: unknown): { message: string; code: string } {
  let message = "API error";
  let code = "api_error";
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: string | { detail?: string; code?: string } })
      .detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      message = detail.detail ?? message;
      code = detail.code ?? code;
    }
  }
  return { message, code };
}

/** Unified fetch with timeout, 429 handling, and optional Zod validation. */
export async function safeFetch<T>(
  path: string,
  options: SafeFetchOptions<T> = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });

  try {
    const response = await fetch(apiUrl(path), {
      method: options.method ?? "GET",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
      },
      body:
        options.body !== undefined ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
    });

    if (!response.ok) {
      let parsed = { message: `API error ${response.status}`, code: "api_error" };
      try {
        parsed = parseApiErrorBody(await response.json());
      } catch {
        // ignore JSON parse errors
      }
      if (response.status === 429) {
        throw new ApiClientError(
          parsed.message || "AI 伺服器目前擁擠（429），請稍後重試。",
          429,
          parsed.code === "api_error" ? "rate_limit" : parsed.code
        );
      }
      if (response.status === 504) {
        throw new ApiClientError(
          parsed.message || "請求逾時，請稍後重試。",
          504,
          "timeout"
        );
      }
      throw new ApiClientError(parsed.message, response.status, parsed.code);
    }

    const raw: unknown = await response.json();
    if (options.schema) {
      const validated = options.schema.safeParse(raw);
      if (!validated.success) {
        throw new ApiClientError(
          `資料驗證失敗：${validated.error.issues.map((i) => i.message).join("; ")}`,
          502,
          "validation_error"
        );
      }
      return validated.data;
    }
    return raw as T;
  } catch (error) {
    if (error instanceof ApiClientError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("請求已取消或逾時。", 504, "timeout");
    }
    throw new ApiClientError(
      error instanceof Error ? error.message : "Network error",
      503,
      "network_error"
    );
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

export function parseTickerList(input: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const token of input.split(/[,;\s\n]+/)) {
    const sym = token.trim().toUpperCase();
    if (sym && !seen.has(sym)) {
      seen.add(sym);
      out.push(sym);
    }
  }
  return out;
}

function mockAnalyzeResponse(
  ticker: string,
  mode: StrategyMode
): AnalyzeResponse {
  const mock = getMockDashboardData(mode);
  const scorecard: ScorecardResult = {
    ...mock.scorecard,
    symbol: ticker.toUpperCase(),
  };
  return {
    scorecard,
    redTeamFindings: mock.redTeamFindings,
    analystCommentary: null,
    dataSource: "mock",
  };
}

function mockNarrativeResponse(
  ticker: string,
  mode: StrategyMode
): NarrativeResponse {
  const mock = getMockDashboardData(mode);
  return {
    symbol: ticker.toUpperCase(),
    text: `（Mock）${mock.scorecard.companyName} 科技敘事 placeholder`,
    liveNewsDegraded: false,
    strategyMode: mode,
  };
}

function shouldUseMockFallback(explicit?: boolean): boolean {
  if (explicit === false) return false;
  if (explicit === true) return true;
  return ENABLE_MOCK_FALLBACK;
}

export async function fetchAnalyze(
  ticker: string,
  mode: StrategyMode,
  options?: { fallbackToMock?: boolean; signal?: AbortSignal }
): Promise<AnalyzeResponse> {
  const sym = ticker.toUpperCase();
  const useMock = shouldUseMockFallback(options?.fallbackToMock);

  try {
    const data = await safeFetch<AnalyzeResponse>(
      `/api/v1/analyze/${encodeURIComponent(sym)}?mode=${mode}`,
      { signal: options?.signal }
    );
    return {
      ...data,
      redTeamFindings: data.redTeamFindings ?? [],
      dataSource: data.dataSource ?? "live",
    };
  } catch (error) {
    if (!useMock) throw error;
    console.warn(`[api] analyze fallback for ${sym}:`, error);
    return mockAnalyzeResponse(sym, mode);
  }
}

export async function fetchNarrative(
  ticker: string,
  mode: StrategyMode,
  options?: { fallbackToMock?: boolean; signal?: AbortSignal }
): Promise<NarrativeResponse> {
  const sym = ticker.toUpperCase();
  const useMock = shouldUseMockFallback(options?.fallbackToMock);

  try {
    return await safeFetch<NarrativeResponse>(
      `/api/v1/narrative/${encodeURIComponent(sym)}?mode=${mode}`,
      { signal: options?.signal, schema: narrativeResponseSchema }
    );
  } catch (error) {
    if (!useMock) throw error;
    console.warn(`[api] narrative fallback for ${sym}:`, error);
    return mockNarrativeResponse(sym, mode);
  }
}

export function analyzeToWatchlistEntry(
  response: AnalyzeResponse
): WatchlistEntry {
  const { scorecard } = response;
  return {
    symbol: scorecard.symbol,
    companyName: scorecard.companyName,
    qualityScore: scorecard.quality.value,
    valuationScore: scorecard.valuation.value,
    grade: `${scorecard.quality.gradeEmoji} ${scorecard.quality.grade}`.trim(),
  };
}

export function sanitizeRedTeamFindings(
  findings: RedTeamFinding[] | null | undefined
): RedTeamFinding[] {
  if (!findings?.length) return [];
  return findings.filter(
    (f) => f?.title?.trim() && f?.description?.trim()
  );
}

export interface StockAnalysisResult {
  data: AnalyzeResponse;
  usedMock: boolean;
  apiError: string | null;
  validationError: string | null;
  fetchedAt: string;
}

/** Server-safe analyze fetch with Zod validation + optional mock fallback. */
export async function getStockAnalysis(
  ticker: string,
  mode: StrategyMode
): Promise<StockAnalysisResult> {
  const { safeParseAnalyzeResponse } = await import("@/lib/schemas");

  const sym = ticker.toUpperCase().trim();
  const fetchedAt = new Date().toISOString();
  let apiError: string | null = null;
  let validationError: string | null = null;

  try {
    const raw = await safeFetch<unknown>(
      `/api/v1/analyze/${encodeURIComponent(sym)}?mode=${mode}`
    );
    const parsed = safeParseAnalyzeResponse(raw);
    if (parsed.success) {
      return {
        data: {
          ...parsed.data,
          redTeamFindings: sanitizeRedTeamFindings(parsed.data.redTeamFindings),
          dataSource: parsed.data.dataSource ?? "live",
        },
        usedMock: false,
        apiError: null,
        validationError: null,
        fetchedAt,
      };
    }
    validationError = parsed.error;
    console.warn(`[api] validation failed for ${sym}:`, parsed.error);
  } catch (error) {
    apiError =
      error instanceof ApiClientError
        ? error.message
        : error instanceof Error
          ? error.message
          : "Unknown API error";
    console.warn(`[api] analyze failed for ${sym}:`, apiError);
  }

  if (!shouldUseMockFallback()) {
    throw new ApiClientError(
      apiError ?? validationError ?? "無法取得分析資料",
      503,
      "api_unavailable"
    );
  }

  return {
    data: mockAnalyzeResponse(sym, mode),
    usedMock: true,
    apiError,
    validationError,
    fetchedAt,
  };
}

export function hasDeathPenalty(data: AnalyzeResponse): boolean {
  const critical = data.redTeamFindings?.some((f) => f.severity === "critical");
  const capped = (data.scorecard.quality.value ?? 0) <= 69;
  return Boolean(critical || capped);
}

/** POST /api/v1/hunter/scan — returns task_id for polling. */
export async function startHunterScan(
  request: HunterScanRequest,
  options?: { signal?: AbortSignal }
): Promise<HunterScanTaskCreated> {
  return safeFetch<HunterScanTaskCreated>("/api/v1/hunter/scan", {
    method: "POST",
    body: {
      universe: request.universe,
      tickers: request.tickers ?? [],
      mode: request.mode,
      minDropPercent: request.minDropPercent,
      enrichScores: request.enrichScores ?? true,
      enrichTags: request.enrichTags ?? false,
    },
    signal: options?.signal,
    timeoutMs: 30_000,
    schema: hunterScanTaskCreatedSchema,
  });
}

/** GET /api/v1/hunter/status/{task_id} */
export async function getHunterTaskStatus(
  taskId: string,
  options?: { signal?: AbortSignal }
): Promise<HunterTaskStatus> {
  return safeFetch<HunterTaskStatus>(
    `/api/v1/hunter/status/${encodeURIComponent(taskId)}`,
    {
      signal: options?.signal,
      timeoutMs: 15_000,
      schema: hunterTaskStatusSchema,
    }
  );
}

/** DELETE /api/v1/hunter/status/{task_id} — cancel scan polling */
export async function cancelHunterTask(
  taskId: string,
  options?: { signal?: AbortSignal }
): Promise<HunterTaskStatus> {
  return safeFetch<HunterTaskStatus>(
    `/api/v1/hunter/status/${encodeURIComponent(taskId)}`,
    {
      method: "DELETE",
      signal: options?.signal,
      timeoutMs: 10_000,
      schema: hunterTaskStatusSchema,
    }
  );
}

/** @deprecated Use startHunterScan + polling. Kept for compatibility. */
export async function runHunterScan(
  request: HunterScanRequest,
  options?: { signal?: AbortSignal }
): Promise<HunterScanResponse> {
  const created = await startHunterScan(request, options);
  const deadline = Date.now() + 300_000;
  while (Date.now() < deadline) {
    if (options?.signal?.aborted) {
      throw new ApiClientError("請求已取消。", 499, "cancelled");
    }
    const status = await getHunterTaskStatus(created.taskId, options);
    if (status.status === "completed" && status.result) {
      return hunterScanResponseSchema.parse(status.result);
    }
    if (status.status === "failed") {
      throw new ApiClientError(
        status.error ?? "掃描失敗",
        503,
        status.errorCode ?? "scan_failed"
      );
    }
    if (status.status === "cancelled") {
      throw new ApiClientError("掃描已取消。", 499, "cancelled");
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new ApiClientError("掃描逾時，請稍後重試。", 504, "timeout");
}

/** Server-safe narrative fetch with validation + empty fallback (never cache poison). */
export async function getStockNarrative(
  ticker: string,
  mode: StrategyMode
): Promise<NarrativeResult> {
  const sym = ticker.toUpperCase().trim();
  const fetchedAt = new Date().toISOString();
  let apiError: string | null = null;

  try {
    const parsed = await safeFetch<NarrativeResponse>(
      `/api/v1/narrative/${encodeURIComponent(sym)}?mode=${mode}`,
      { schema: narrativeResponseSchema }
    );
    const text = isPoisonedNarrative(parsed.text) ? "" : parsed.text.trim();
    return {
      data: { ...parsed, text },
      usedMock: false,
      apiError: null,
      fetchedAt,
    };
  } catch (error) {
    apiError =
      error instanceof ApiClientError
        ? error.message
        : error instanceof Error
          ? error.message
          : "Unknown API error";
  }

  if (shouldUseMockFallback()) {
    return {
      data: mockNarrativeResponse(sym, mode),
      usedMock: true,
      apiError,
      fetchedAt,
    };
  }

  return {
    data: {
      symbol: sym,
      text: "",
      liveNewsDegraded: false,
      strategyMode: mode,
    },
    usedMock: false,
    apiError,
    fetchedAt,
  };
}

export { apiUrl, ENABLE_MOCK_FALLBACK };
