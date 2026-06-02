"use client";

import Link from "next/link";

export default function StockError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-8 text-center">
      <h1 className="text-xl font-semibold text-destructive">載入失敗</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        {error.message || "無法載入個股分析資料，請稍後重試。"}
      </p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={reset}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          重試
        </button>
        <Link
          href="/"
          className="rounded-md border border-border px-4 py-2 text-sm font-medium"
        >
          返回 Dashboard
        </Link>
      </div>
    </main>
  );
}
