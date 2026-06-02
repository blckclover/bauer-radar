import { z } from "zod";

import type { AnalyzeResponse, StrategyMode } from "@/types";

export const strategyModeSchema = z.enum(["value", "growth"]);

export const qualityScoreSchema = z.object({
  value: z.number(),
  max: z.number().default(100),
  label: z.string().default("企業品質分"),
  grade: z.string().default(""),
  gradeEmoji: z.string().default(""),
});

export const valuationScoreSchema = z.object({
  value: z.number(),
  max: z.number().default(100),
  label: z.string().default("估值安全邊際"),
});

export const scoreDimensionSchema = z.object({
  id: z.string(),
  label: z.string(),
  earned: z.number(),
  maxPoints: z.number(),
  weightPct: z.number(),
  rationale: z.string().optional().nullable(),
});

export const metricItemSchema = z.object({
  id: z.string(),
  label: z.string(),
  value: z.string(),
  subtext: z.string().optional().nullable(),
  tooltip: z.string().optional().nullable(),
});

export const redTeamFindingSchema = z.object({
  id: z.string(),
  severity: z.enum(["critical", "warning", "info"]),
  title: z.string(),
  description: z.string(),
  metric: z.string().optional().nullable(),
});

export const scorecardResultSchema = z.object({
  symbol: z.string(),
  companyName: z.string(),
  strategyMode: strategyModeSchema,
  quality: qualityScoreSchema,
  valuation: valuationScoreSchema,
  dimensions: z.array(scoreDimensionSchema).default([]),
  metrics: z.array(metricItemSchema).default([]),
});

export const analyzeResponseSchema = z.object({
  scorecard: scorecardResultSchema,
  redTeamFindings: z.array(redTeamFindingSchema).default([]),
  analystCommentary: z.string().nullable().optional(),
  fcfHistory: z
    .array(
      z.object({
        fiscalYear: z.number(),
        freeCashFlow: z.number(),
        periodEnd: z.string().optional(),
        source: z.string().optional(),
      })
    )
    .default([]),
  dataSource: z.enum(["live", "cache", "mock"]).optional(),
});

export const narrativeResponseSchema = z.object({
  symbol: z.string(),
  text: z.string().default(""),
  liveNewsDegraded: z.boolean().default(false),
  strategyMode: strategyModeSchema,
});

export const turnaroundCandidateSchema = z.object({
  symbol: z.string(),
  companyName: z.string(),
  drawdownPct: z.number(),
  currentPrice: z.number(),
  sixMonthHigh: z.number(),
  latestFcf: z.number(),
  latestFcfFiscalYear: z.number().nullable().optional(),
  fcfSource: z.string().optional(),
  interestCoverage: z.number().nullable().optional(),
  grossMargin: z.number().nullable().optional(),
  grossMarginYoyChangePp: z.number().nullable().optional(),
  netDebtEbitda: z.number().nullable().optional(),
  fiftyTwoWeekHigh: z.number().nullable().optional(),
  priceVs52wHigh: z.number().nullable().optional(),
  pegRatio: z.number().nullable().optional(),
  valueDefenseScore: z.number().nullable().optional(),
  valueGradeEmoji: z.string().optional(),
  valueGradeLabel: z.string().optional(),
  reasonTag: z.string().optional(),
  reasonComment: z.string().optional(),
  redTeamFlag: z.boolean().default(false),
});

export const hunterScanResponseSchema = z.object({
  candidates: z.array(turnaroundCandidateSchema).default([]),
  scannedCount: z.number(),
  hitCount: z.number(),
  universe: z.string(),
  universeSource: z.string(),
  minDropPercent: z.number(),
});

export const hunterScanTaskCreatedSchema = z.object({
  taskId: z.string(),
});

export const hunterTaskStatusSchema = z.object({
  taskId: z.string(),
  status: z.enum(["pending", "running", "completed", "failed", "cancelled"]),
  progress: z.number().default(0),
  message: z.string().default(""),
  result: hunterScanResponseSchema.nullable().optional(),
  error: z.string().nullable().optional(),
  errorCode: z.string().nullable().optional(),
  updatedAt: z.string().nullable().optional(),
});

export type AnalyzeResponseValidated = z.infer<typeof analyzeResponseSchema>;

export function parseStrategyMode(raw: string | string[] | undefined): StrategyMode {
  const value = Array.isArray(raw) ? raw[0] : raw;
  const parsed = strategyModeSchema.safeParse(value);
  return parsed.success ? parsed.data : "value";
}

export function parseAnalyzeResponse(raw: unknown): AnalyzeResponse {
  return analyzeResponseSchema.parse(raw) as AnalyzeResponse;
}

export function safeParseAnalyzeResponse(
  raw: unknown
): { success: true; data: AnalyzeResponse } | { success: false; error: string } {
  const result = analyzeResponseSchema.safeParse(raw);
  if (result.success) {
    return { success: true, data: result.data as AnalyzeResponse };
  }
  return {
    success: false,
    error: result.error.issues.map((i) => i.message).join("; "),
  };
}
