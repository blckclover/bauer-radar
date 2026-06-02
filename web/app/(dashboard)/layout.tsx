import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dashboard · 股息安全分析",
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
