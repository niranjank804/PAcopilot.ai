import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

/**
 * The fallback for everything that is not an Apple device.
 *
 * The type stack in globals.css asks for San Francisco first, which only
 * macOS and iOS can supply. Self-hosting Inter means the other 70% of an
 * enterprise desktop estate gets a typeface with the same tight metrics
 * instead of dropping to Arial, and next/font inlines it with no network
 * request and no layout shift.
 */
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "PA-Copilot — AI Copilot for IBM Planning Analytics",
  description: "AI engineering copilot for IBM Planning Analytics/TM1",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
