import type {
  AnalyzeResponse,
  NarrativeResponse,
  RedTeamFinding,
  ScorecardResult,
  StrategyMode,
  WatchlistEntry,
} from "@/types";
import { getMockDashboardData } from "@/lib/mockData";

const DEFAULT_TIMEOUT_MS = 120_000;

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

async function fetchJson<T>(
  path: string,
  options?: { signal?: AbortSignal; timeoutMs?: number }
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    options?.timeoutMs ?? DEFAULT_TIMEOUT_MS
  );

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      signal: options?.signal ?? controller.signal,
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    if (!response.ok) {
      let message = `API error ${response.status}`;
      let code = "api_error";
      try {
        const body = (await response.json()) as {
          detail?: string | { detail?: string; code?: string };
        };
        if (typeof body.detail === "string") {
          message = body.detail;
        } else if (body.detail && typeof body.detail === "object") {
          message = body.detail.detail ?? message;
          code = body.detail.code ?? code;
        }
      } catch {
        // ignore JSON parse errors
      }
      throw new ApiClientError(message, response.status, code);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiClientError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError("請求逾時，請稍後重試。", 504, "timeout");
    }
    throw new ApiClientError(
      error instanceof Error ? error.message : "Network error",
      503,
      "network_error"
    );
  } finally {
    clearTimeout(timeout);
  }
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

export async function fetchAnalyze(
  ticker: string,
  mode: StrategyMode,
  options?: { fallbackToMock?: boolean; signal?: AbortSignal }
): Promise<AnalyzeResponse> {
  const sym = ticker.toUpperCase();
  const useMock = options?.fallbackToMock !== false;

  try {
    const data = await fetchJson<AnalyzeResponse>(
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
  const useMock = options?.fallbackToMock !== false;

  try {
    return await fetchJson<NarrativeResponse>(
      `/api/v1/narrative/${encodeURIComponent(sym)}?mode=${mode}`,
      { signal: options?.signal }
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
}

/** Server-safe analyze fetch with Zod validation + mock fallback. */
export async function getStockAnalysis(
  ticker: string,
  mode: StrategyMode
): Promise<StockAnalysisResult> {
  const { parseAnalyzeResponse, safeParseAnalyzeResponse } = await import(
    "@/lib/schemas"
  );

  const sym = ticker.toUpperCase().trim();
  let apiError: string | null = null;
  let validationError: string | null = null;

  try {
    const raw = await fetchJson<unknown>(
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

  const mock = mockAnalyzeResponse(sym, mode);
  try {
    const validated = parseAnalyzeResponse(mock);
    return {
      data: validated,
      usedMock: true,
      apiError,
      validationError,
    };
  } catch {
    return {
      data: mock,
      usedMock: true,
      apiError,
      validationError,
    };
  }
}

export function hasDeathPenalty(
  data: AnalyzeResponse
): boolean {
  const critical = data.redTeamFindings?.some((f) => f.severity === "critical");
  const capped = (data.scorecard.quality.value ?? 0) <= 69;
  return Boolean(critical || capped);
}
