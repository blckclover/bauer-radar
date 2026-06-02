import Link from "next/link";

export default function StockNotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-8 text-center">
      <h1 className="text-2xl font-bold text-foreground">找不到此標的</h1>
      <p className="text-sm text-muted-foreground">
        股票代號格式無效或不存在。
      </p>
      <Link href="/" className="text-sm font-medium text-primary hover:underline">
        返回 Dashboard
      </Link>
    </main>
  );
}
