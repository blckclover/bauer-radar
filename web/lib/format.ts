/** Display formatting helpers — no business logic. */

export function formatMoneyLarge(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  const v = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (v >= 1e9) return `${sign}$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${sign}$${(v / 1e6).toFixed(0)}M`;
  return `${sign}$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function formatPctOffHigh(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "—";
  return `-${((1 - ratio) * 100).toFixed(1)}%`;
}

export function formatCoverage(value: number | null | undefined): string {
  if (value === null || value === undefined) return "低負債";
  return `${value.toFixed(1)}x`;
}

export function formatGrossMargin(
  margin: number | null | undefined,
  yoyPp: number | null | undefined
): string {
  if (margin === null || margin === undefined) return "—";
  let text = `${margin.toFixed(1)}%`;
  if (yoyPp !== null && yoyPp !== undefined) {
    const sign = yoyPp >= 0 ? "+" : "";
    text += ` (YoY ${sign}${yoyPp.toFixed(1)}pp)`;
  }
  return text;
}

export function isPoisonedNarrative(text: string | null | undefined): boolean {
  if (!text?.trim()) return true;
  const lower = text.toLowerCase();
  return (
    text.startsWith("⚠️") ||
    lower.includes("429") ||
    lower.includes("resource_exhausted") ||
    lower.includes("生成失敗")
  );
}
