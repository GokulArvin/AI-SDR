import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { PageTransition } from "@/components/PageTransition";
import { Sidebar } from "@/components/Sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI-SDR",
  description: "AI-powered Sales Development Representative",
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
      // The theme script below sets data-theme on this element before React hydrates,
      // which will never match the server-rendered markup -- that's expected here, not
      // a real bug, so suppress the hydration warning instead of the two colliding.
      suppressHydrationWarning
    >
      <head>
        {/* Runs before paint so the manually-chosen theme applies immediately,
            instead of flashing the OS-default theme first. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try {
              var t = localStorage.getItem('theme');
              if (t) document.documentElement.setAttribute('data-theme', t);
            } catch (e) {}`,
          }}
        />
      </head>
      <body className="min-h-full flex">
        <Sidebar />
        <main className="flex-1 min-w-0">
          <div className="max-w-5xl mx-auto px-8 py-10">
            <PageTransition>{children}</PageTransition>
          </div>
        </main>
      </body>
    </html>
  );
}
