import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { QueryProvider } from "@/components/providers/QueryProvider";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "股息安全 · 綜合分析儀表板",
  description:
    "Institutional-grade dividend & FCF scoring dashboard — Next.js migration Phase 1",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant" className="dark">
      <body className={`${inter.variable} min-h-screen font-sans antialiased`}>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
