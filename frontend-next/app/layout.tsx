import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { LocaleProvider } from "@/lib/i18n";
import { DEFAULT_LOCALE } from "@/lib/i18n-core";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Sentinel OSINT Dashboard",
  description: "Geopolitical OSINT monitoring dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang={DEFAULT_LOCALE} className={`${geistSans.variable} ${geistMono.variable}`}>
      <body><AuthProvider><LocaleProvider>{children}</LocaleProvider></AuthProvider></body>
    </html>
  );
}
