import { Skeleton } from "@/components/ui/skeleton";

export default function ReversalScanLoading() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/60 px-6 py-8">
        <Skeleton className="mb-4 h-4 w-32" />
        <Skeleton className="h-9 w-64" />
        <Skeleton className="mt-2 h-5 w-96" />
      </header>
      <main className="mx-auto max-w-7xl space-y-8 p-8">
        <Skeleton className="h-48 rounded-lg" />
        <Skeleton className="h-12 w-64 rounded-lg" />
        <Skeleton className="h-96 rounded-lg" />
      </main>
    </div>
  );
}
