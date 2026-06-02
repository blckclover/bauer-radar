import { notFound } from "next/navigation";

import { StockDetailView } from "@/components/stock/StockDetailView";
import { getStockAnalysis, getStockNarrative } from "@/lib/api";
import { parseStrategyMode } from "@/lib/schemas";

interface StockPageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ mode?: string }>;
}

const TICKER_RE = /^[A-Za-z][A-Za-z0-9.\-]{0,9}$/;

export default async function StockPage({ params, searchParams }: StockPageProps) {
  const { ticker } = await params;
  const { mode: rawMode } = await searchParams;

  if (!TICKER_RE.test(ticker)) {
    notFound();
  }

  const mode = parseStrategyMode(rawMode);
  const [result, narrative] = await Promise.all([
    getStockAnalysis(ticker, mode),
    getStockNarrative(ticker, mode),
  ]);

  return (
    <StockDetailView
      ticker={ticker.toUpperCase()}
      mode={mode}
      result={result}
      narrative={narrative}
    />
  );
}

export async function generateMetadata({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  const symbol = ticker.toUpperCase();
  return {
    title: `${symbol} · 個股深度分析`,
    description: `Institutional dual-track scoring for ${symbol}`,
  };
}
