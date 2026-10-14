import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible, Victor_Mono } from "next/font/google";
import "./globals.css";

const text = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-atkinson",
  display: "swap",
});

const code = Victor_Mono({
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
  variable: "--font-victor",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AFL Copilot: AmiBroker code you can check",
  description:
    "Describe a trading strategy and get AmiBroker AFL that has been checked for invented functions, look-ahead and the other mistakes that quietly ruin a backtest.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfcf8" },
    { media: "(prefers-color-scheme: dark)", color: "#16201d" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${text.variable} ${code.variable}`}>
      <body>{children}</body>
    </html>
  );
}
