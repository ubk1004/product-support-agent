import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Product Support Agent",
  description:
    "A local-first product support assistant grounded in approved documentation.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
