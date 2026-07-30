import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Research Copilot",
  description:
    "Map an ML research field from a single search — arXiv retrieval, reranking, structured summaries, and a growing reading map.",
  // Added to the iPad home screen, this opens without Safari's chrome, which
  // matters more than it sounds: the browser toolbars eat vertical space on
  // every reading view, and a stray edge swipe navigates away mid-annotation.
  appleWebApp: { capable: true, title: "Research Copilot", statusBarStyle: "default" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">{children}</body>
    </html>
  );
}
