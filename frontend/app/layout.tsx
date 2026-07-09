export const metadata = {
  title: "TradingPlatform Dashboard",
  description: "Fase 1 skeleton frontend - consumes only the gateway service.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
