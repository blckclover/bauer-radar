"use client";

import { useQuery, useQueries } from "@tanstack/react-query";

import {
  analyzeToWatchlistEntry,
  fetchAnalyze,
  parseTickerList,
  sanitizeRedTeamFindings,
} from "@/lib/api";
import type { AnalyzeResponse, StrategyMode, WatchlistEntry } from "@/types";

const STALE_TIME_MS = 60 * 60 * 1000;

export function useAnalyzeQuery(ticker: string, mode: StrategyMode) {
  return useQuery({
    queryKey: ["analyze", ticker, mode] as const,
    queryFn: ({ signal }) => fetchAnalyze(ticker, mode, { signal }),
    enabled: Boolean(ticker),
    staleTime: STALE_TIME_MS,
    retry: (failureCount, error) => {
      if (failureCount >= 1) return false;
      if (error && typeof error === "object" && "status" in error) {
        const status = (error as { status: number }).status;
        if (status === 400 || status === 429) return false;
      }
      return true;
    },
  });
}

export function useWatchlistQueries(tickers: string[], mode: StrategyMode) {
  return useQueries({
    queries: tickers.map((ticker) => ({
      queryKey: ["analyze", ticker, mode] as const,
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        fetchAnalyze(ticker, mode, { signal }),
      enabled: Boolean(ticker),
      staleTime: STALE_TIME_MS,
      retry: 1,
    })),
  });
}

export function buildWatchlistFromQueries(
  queries: ReturnType<typeof useWatchlistQueries>
): WatchlistEntry[] {
  const entries: WatchlistEntry[] = [];
  for (const q of queries) {
    if (q.data?.scorecard) {
      entries.push(analyzeToWatchlistEntry(q.data as AnalyzeResponse));
    }
  }
  return entries;
}

export function extractHeroData(query: ReturnType<typeof useAnalyzeQuery>) {
  const scorecard = query.data?.scorecard;
  const redTeamFindings = sanitizeRedTeamFindings(query.data?.redTeamFindings);
  const isMock = query.data?.dataSource === "mock";
  const isRateLimited =
    query.error &&
    typeof query.error === "object" &&
    "code" in query.error &&
    (query.error as { code: string }).code === "rate_limit";

  return {
    scorecard,
    redTeamFindings,
    isMock,
    isRateLimited,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}

export { parseTickerList };
