export const metadata = {
  title: "SHNQ Admin Dashboard Overview",
  description: "SHNQ standards portal admin dashboard",
};

import "@fontsource/material-symbols-outlined";
import "./globals.css";

export default function RootLayout({ children }) {
  return (
    <html className="light" lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-background-light font-display text-slate-900 antialiased min-h-screen dark:bg-background-dark dark:text-slate-100">
        {children}
      </body>
    </html>
  );
}
