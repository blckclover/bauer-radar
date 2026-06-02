import Link from "next/link";

interface StockPageProps {
  params: Promise<{ ticker: string }>;
}

export default async function StockPage({ params }: StockPageProps) {
  const { ticker } = await params;
  const symbol = ticker.toUpperCase();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-8 text-center">
      <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
        Phase 2 · Stock Detail Route
      </p>
      <h1 className="text-3xl font-bold text-foreground">{symbol}</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        個股深度分析頁面將於第二階段實作，包含 Scorecard、Red Team 與 AI 敘事區塊。
      </p>
      <Link
        href="/"
        className="text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        返回 Dashboard
      </Link>
    </main>
  );
}
