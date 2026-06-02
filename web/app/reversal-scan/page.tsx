import { ReversalScanWorkspace } from "@/components/reversal-scan/ReversalScanWorkspace";
import { parseStrategyMode } from "@/lib/schemas";

interface ReversalScanPageProps {
  searchParams: Promise<{ mode?: string }>;
}

export default async function ReversalScanPage({
  searchParams,
}: ReversalScanPageProps) {
  const { mode: rawMode } = await searchParams;
  const mode = parseStrategyMode(rawMode);

  return <ReversalScanWorkspace initialMode={mode} />;
}

export const metadata = {
  title: "逆向轉機股雷達 · Reversal Scan",
  description: "Institutional turnaround radar — drawdown + FCF + defensive filters",
};
