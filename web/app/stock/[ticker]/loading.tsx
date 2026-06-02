import { Skeleton } from "@/components/ui/skeleton";

export default function StockLoading() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/60 bg-card/30 px-4 py-8 sm:px-6">
        <Skeleton className="mb-4 h-4 w-32" />
        <Skeleton className="mb-2 h-8 w-48" />
        <Skeleton className="h-5 w-72" />
        <Skeleton className="mt-6 h-10 w-full max-w-md" />
      </header>
      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-52 rounded-lg" />
          <Skeleton className="h-52 rounded-lg" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-40 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
      </main>
    </div>
  );
}
