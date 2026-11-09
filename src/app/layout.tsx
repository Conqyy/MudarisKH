import type { Metadata } from "next";
import "./globals.css";
import "./workspace-pages.css";
import "@/components/material-ui.css";
import "./glass-shell.css";
import { AuthProvider } from "@/lib/auth-context";
import { LanguageProvider } from "@/lib/i18n";
import { SidebarProvider } from "@/lib/sidebar";
import { InputModalityProvider } from "@/lib/input-modality";

export const metadata: Metadata = {
  title: "Mudaris — AI Study Assistant",
  description:
    "Your course materials, connected. Study with source-grounded exams, summaries, flashcards and a personal AI tutor.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // English / LTR is the default; the client switches to ar/rtl if the user
  // previously chose Arabic (LanguageProvider updates <html> on mount).
  return (
    <html lang="en" dir="ltr" data-theme="light" suppressHydrationWarning>
      <head>
        {/* Apply saved navigation preferences before first paint. The visual
            theme is always light, including for older saved dark preferences. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var s=localStorage.getItem('mudaris_sidebar');document.documentElement.dataset.sidebar=s==='expanded'?'expanded':'collapsed'}catch(e){document.documentElement.dataset.sidebar='collapsed'}" +
              "try{var l=localStorage.getItem('mudaris_lang');document.documentElement.lang=l==='ar'?'ar':'en';document.documentElement.dir=l==='ar'?'rtl':'ltr'}catch(e){}",
          }}
        />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        {/* App Router's root layout is the shared document for every page. */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Alexandria:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased" suppressHydrationWarning>
        <LanguageProvider>
          <SidebarProvider>
            <InputModalityProvider><AuthProvider>{children}</AuthProvider></InputModalityProvider>
          </SidebarProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
