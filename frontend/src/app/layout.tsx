import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ArbitMint | Testnet Demo",
  description:
    "Read-only cross-venue market estimates. Wallet connection is optional; no swaps are submitted.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="persistent-ribbon" role="note" aria-label="Environment and data labels">
          <span className="ribbon-title">ARBITMINT LAB</span>
          <span className="ribbon-item"><i className="dot dot-cyan" /> TESTNET · UNICHAIN SEPOLIA</span>
          <span className="ribbon-item"><i className="dot dot-violet" /> WALLET OPTIONAL · NO TOKEN SPEND</span>
          <span className="ribbon-item"><i className="dot dot-amber" /> READ-ONLY MARKET ESTIMATES</span>
        </div>
        {children}
      </body>
    </html>
  );
}
