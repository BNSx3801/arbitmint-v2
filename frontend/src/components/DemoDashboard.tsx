"use client";

import { useEffect, useState } from "react";
import { formatBaseUnits } from "@/lib/format";

type Asset = { symbol: string; name: string; pair: string };
type Quote = {
  status: "available";
  asset: string;
  amount_in_usdc_base_units: string;
  v4_amount_out_base_units: string;
  token_decimals: number;
  binance_gross_sale_usdc_base_units: string;
  binance_fee_usdc_base_units: string;
  estimated_pnl_usdc_base_units: string;
  fee_assumption_bps: number;
  binance_pair: string;
  sources: { binance_received_at: string; unichain_block_number: number; unichain_block_timestamp: string };
};
type Snapshot = { asset: string; net: bigint; at: string };
type WalletProvider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  connect?: () => Promise<unknown>;
  disconnect?: () => Promise<void>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  removeListener: (event: string, listener: (...args: unknown[]) => void) => void;
};
type DiscoveredWallet = { info: { uuid: string; name: string; icon: string; rdns: string }; provider: WalletProvider };

declare global {
  interface Window { ethereum?: WalletProvider }
}

const API_URL = (
  process.env.NEXT_PUBLIC_MARKET_API_URL ||
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "")
).replace(/\/$/, "");

function apiError(error: unknown, action: string): string {
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    const endpoint = API_URL || "the same origin";
    return `Market API at ${endpoint} is unreachable. Check the backend deployment; this is separate from wallet connection.`;
  }
  return error instanceof Error ? error.message : `${action} failed.`;
}

function parseUsdc(value: string): bigint {
  const match = /^(\d*)(?:\.(\d{0,6})?)?$/.exec(value.trim());
  if (!match || (!match[1] && !match[2])) return 0n;
  return BigInt(match[1] || "0") * 1_000_000n + BigInt((match[2] || "").padEnd(6, "0") || "0");
}

function usdPrice(value: bigint): string {
  return `$${formatBaseUnits(value, 6, 2)}`;
}

export function DemoDashboard() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [asset, setAsset] = useState("");
  const [budgetText, setBudgetText] = useState("1000");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [assetsError, setAssetsError] = useState<string | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [wallets, setWallets] = useState<DiscoveredWallet[]>([]);
  const [walletProvider, setWalletProvider] = useState<WalletProvider | null>(null);
  const [walletName, setWalletName] = useState<string | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [walletChainId, setWalletChainId] = useState<number | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [walletError, setWalletError] = useState<string | null>(null);
  const walletConnectAvailable = Boolean(process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID);
  const isConnected = Boolean(walletAddress);

  useEffect(() => {
    const announce = (event: Event) => {
      const detail = (event as CustomEvent<DiscoveredWallet>).detail;
      if (!detail?.info?.uuid || !detail.provider) return;
      setWallets((current) => {
        const installed = current.filter((item) => item.info.uuid !== "legacy");
        return installed.some((item) => item.info.uuid === detail.info.uuid) ? installed : [...installed, detail];
      });
    };
    window.addEventListener("eip6963:announceProvider", announce);
    window.dispatchEvent(new Event("eip6963:requestProvider"));
    if (window.ethereum) {
      setWallets([{ info: { uuid: "legacy", name: "Browser wallet", icon: "", rdns: "" }, provider: window.ethereum }]);
    }
    return () => window.removeEventListener("eip6963:announceProvider", announce);
  }, []);

  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/api/market/assets`).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Market asset discovery is unavailable.");
      if (!active) return;
      setAssets(body.assets);
      setAsset((current) => current && body.assets.some((item: Asset) => item.symbol === current) ? current : (body.assets[0]?.symbol || ""));
      setAssetsError(body.assets.length ? null : "No asset currently has both an active Binance USDC market and a configured Uniswap v4 pool.");
    }).catch((error: unknown) => {
      if (active) setAssetsError(apiError(error, "Market asset discovery"));
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!asset) { setQuote(null); return; }
    setQuote(null);
    setQuoteError(null);
    let active = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      setLoadingQuote(true);
      try {
        const params = new URLSearchParams({ asset, amount_usdc: budgetText });
        const response = await fetch(`${API_URL}/api/market/quote?${params}`);
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "A fresh market quote is unavailable.");
        if (active) { setQuote(body); setQuoteError(null); }
      } catch (error) {
        if (active) { setQuote(null); setQuoteError(apiError(error, "Market quote request")); }
      } finally { inFlight = false; if (active) setLoadingQuote(false); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2_500);
    return () => { active = false; window.clearInterval(timer); };
  }, [asset, budgetText]);

  useEffect(() => {
    if (!walletProvider) return;
    const onAccountsChanged = (...args: unknown[]) => {
      const accounts = args[0];
      setWalletAddress(Array.isArray(accounts) && typeof accounts[0] === "string" ? accounts[0] : null);
    };
    const onChainChanged = (...args: unknown[]) => {
      const chain = args[0];
      setWalletChainId(typeof chain === "string" ? Number.parseInt(chain, 16) : typeof chain === "number" ? chain : null);
    };
    walletProvider.on("accountsChanged", onAccountsChanged);
    walletProvider.on("chainChanged", onChainChanged);
    return () => {
      walletProvider.removeListener("accountsChanged", onAccountsChanged);
      walletProvider.removeListener("chainChanged", onChainChanged);
    };
  }, [walletProvider]);

  const budget = parseUsdc(budgetText);
  const estimate = quote ? {
    tokenBaseUnits: BigInt(quote.v4_amount_out_base_units),
    grossSale: BigInt(quote.binance_gross_sale_usdc_base_units),
    venueFee: BigInt(quote.binance_fee_usdc_base_units),
    net: BigInt(quote.estimated_pnl_usdc_base_units),
  } : null;

  function recordPaperTrade() {
    if (estimate) setSnapshot({ asset, net: estimate.net, at: new Date().toLocaleTimeString() });
  }

  const positive = (estimate?.net ?? 0n) >= 0n;

  async function connectInjectedWallet(wallet: DiscoveredWallet) {
    setIsConnecting(true);
    setWalletError(null);
    try {
      const accounts = await wallet.provider.request({ method: "eth_requestAccounts" });
      const chain = await wallet.provider.request({ method: "eth_chainId" });
      const address = Array.isArray(accounts) && typeof accounts[0] === "string" ? accounts[0] : null;
      if (!address) throw new Error("The wallet did not return an account.");
      setWalletAddress(address);
      setWalletChainId(typeof chain === "string" ? Number.parseInt(chain, 16) : null);
      setWalletName(wallet.info.name);
      setWalletProvider(wallet.provider);
    } catch (error) {
      setWalletError(error instanceof Error ? error.message : "Browser wallet connection failed.");
    } finally {
      setIsConnecting(false);
    }
  }

  async function connectWalletConnect() {
    const projectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID;
    if (!projectId) {
      setWalletError("WalletConnect QR needs a free project ID in frontend/.env.local, then restart the frontend.");
      return;
    }
    setIsConnecting(true);
    setWalletError(null);
    try {
      const { default: EthereumProvider } = await import("@walletconnect/ethereum-provider");
      const provider = await EthereumProvider.init({
        projectId,
        chains: [1301],
        showQrModal: true,
        rpcMap: { 1301: "https://sepolia.unichain.org" },
      });
      await provider.connect();
      const accounts = await provider.request({ method: "eth_accounts" });
      const chain = await provider.request({ method: "eth_chainId" });
      const address = Array.isArray(accounts) && typeof accounts[0] === "string" ? accounts[0] : null;
      if (!address) throw new Error("WalletConnect connected without an account.");
      setWalletAddress(address);
      setWalletChainId(typeof chain === "string" ? Number.parseInt(chain, 16) : null);
      setWalletName("WalletConnect");
      setWalletProvider(provider as unknown as WalletProvider);
    } catch (error) {
      setWalletError(error instanceof Error ? error.message : "WalletConnect connection failed.");
    } finally {
      setIsConnecting(false);
    }
  }

  async function disconnectWallet() {
    try { await walletProvider?.disconnect?.(); } finally {
      setWalletAddress(null);
      setWalletChainId(null);
      setWalletName(null);
      setWalletProvider(null);
    }
  }
  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#overview" aria-label="ArbitMint home"><span className="brand-mark">A</span><span>ArbitMint</span><span className="brand-version">PAPER MVP</span></a>
        <nav className="top-nav" aria-label="Main navigation"><a className="nav-active" href="#overview">Markets</a><a href="#simulator">Simulator</a></nav>
        <div className="wallet-control">
          {isConnected ? <>
            <span className={`wallet-status ${walletChainId === 1301 ? "wallet-ok" : "wallet-wrong"}`}>{walletChainId === 1301 ? "Unichain Sepolia" : `Wrong network · ${walletChainId}`}</span>
            <button className="wallet-button" type="button" onClick={() => void disconnectWallet()}>{walletName} · {walletAddress?.slice(0, 6)}…{walletAddress?.slice(-4)} · Disconnect</button>
          </> : <div className="wallet-actions">
            {wallets.length === 0 && <span className="wallet-status">No injected wallet in this browser</span>}
            {wallets.map((wallet) => <button className="wallet-button" type="button" key={wallet.info.uuid} disabled={isConnecting} onClick={() => void connectInjectedWallet(wallet)}>{isConnecting ? "Connecting…" : wallet.info.name}</button>)}
            <button className="wallet-button" type="button" disabled={isConnecting || !walletConnectAvailable} onClick={() => void connectWalletConnect()}>{isConnecting ? "Connecting…" : "WalletConnect QR"}</button>
          </div>}
          {walletError && <span className="wallet-error" role="alert">{walletError}</span>}
        </div>
      </header>

      <section className="page-heading" id="overview">
        <div><div className="eyebrow"><span className="eyebrow-line" /> CROSS-VENUE PAPER SIMULATOR</div><h1>Explore a price gap</h1>
          <p className="page-subtitle">Choose an eligible asset, size a hypothetical USDC buy, and compare a live v4 quote with Binance bid depth.</p></div>
        <div className="demo-stamp"><span className="stamp-icon">◈</span> NO APPROVALS · NO TOKEN SPEND</div>
      </section>

      <section className="notice" aria-label="Market estimate disclosure"><span className="notice-icon">i</span><p><strong>Read-only market estimate.</strong> Binance public order-book data and a Uniswap v4 quote on Unichain Mainnet are used to estimate a hypothetical buy and sale. This is not a trade or verified profit; gas, transfer, withdrawal, and execution costs are excluded. Wallet connection remains optional and is not used for quotes.</p></section>

      <section className="market-toolbar" aria-label="Live market quote sources">
        <div className="market-title"><span className="live-dot" /> READ-ONLY QUOTE <span className="market-caption">refreshes every 2.5 seconds</span></div>
        <div className="market-pair"><span>{asset || "Asset"}/USDC · Uniswap v4 · Unichain Mainnet</span><strong>{quote ? `Block ${quote.sources.unichain_block_number}` : "Unavailable"}</strong></div>
        <div className="market-pair"><span>{quote?.binance_pair || `${asset || "Asset"}USDC`} · Binance Spot bid book</span><strong>{quote ? "Depth priced" : "Unavailable"}</strong></div>
        <div className="market-time">{quote ? `Book ${new Date(quote.sources.binance_received_at).toLocaleTimeString()}` : loadingQuote ? "Fetching sources…" : "Waiting for valid source data"}</div>
      </section>

      <div className="trade-grid" id="simulator">
        <section className="panel trade-panel">
          <div className="panel-heading"><div><div className="eyebrow">SCENARIO INPUT</div><h2>Configure a paper trade</h2></div><span className="readonly-chip">LOCAL ONLY</span></div>
          <label className="field-label" htmlFor="asset">Asset paired with USDC</label>
          <div className="asset-picker" role="group" aria-label="Select asset">
            {assets.map((item) => <button type="button" key={item.symbol} onClick={() => { setAsset(item.symbol); setSnapshot(null); }} className={`asset-option ${asset === item.symbol ? "asset-selected" : ""}`} aria-pressed={asset === item.symbol}>
              <span className="asset-symbol">{item.symbol}</span><span className="asset-name">{item.pair} · Binance + v4</span>
            </button>)}
          </div>
          {assetsError && <p className="wallet-error">{assetsError}</p>}
          {!assets.length && !assetsError && <p className="field-help">Loading eligible assets…</p>}
          <label className="field-label" htmlFor="budget">Hypothetical USDC buy size</label>
          <div className="amount-input-wrap"><input id="budget" inputMode="decimal" value={budgetText} onChange={(event) => setBudgetText(event.target.value)} aria-describedby="budget-help" /><span>USDC</span></div>
          <p className="field-help" id="budget-help">Display-only input. No wallet balance is read and no funds are used.</p>
          <button type="button" className="primary-button simulate-button" disabled={budget <= 0n || !estimate} onClick={recordPaperTrade}>Record estimate snapshot <span aria-hidden="true">→</span></button>
          {!walletConnectAvailable && <p className="field-help">Injected wallets are detected automatically. To pair a mobile wallet by QR, set a free WalletConnect project ID in frontend/.env.local and restart the frontend.</p>}
        </section>

        <section className="panel result-panel" aria-live="polite">
          <div className="panel-heading"><div><div className="eyebrow">MOMENTARY OUTCOME <span className="data-label data-label-estimate">ESTIMATE</span></div><h2>Estimated profit / loss</h2></div><span className="pulse-chip"><i /> {loadingQuote ? "REFRESHING" : "2.5S REFRESH"}</span></div>
          {estimate ? <>
          <div className={`pnl-value ${positive ? "pnl-positive" : "pnl-negative"}`}>{positive ? "+" : "−"}{usdPrice(estimate.net < 0n ? -estimate.net : estimate.net)}</div>
          <div className={`pnl-verdict ${positive ? "verdict-positive" : "verdict-negative"}`}>{positive ? "Potential profit at this estimated moment" : "Potential loss at this estimated moment"}</div>
          <div className="result-breakdown">
            <div><span>Hypothetical {asset} acquired · v4 quote</span><strong>{formatBaseUnits(estimate.tokenBaseUnits, quote!.token_decimals, 6)} {asset}</strong></div>
            <div><span>Binance bid-depth sale value</span><strong>{usdPrice(estimate.grossSale)}</strong></div>
            <div><span>Less assumed Binance taker fee · {quote!.fee_assumption_bps / 100}%</span><strong>−{usdPrice(estimate.venueFee)}</strong></div>
            <div className="result-total"><span>Estimated net vs. USDC input</span><strong className={positive ? "pnl-positive" : "pnl-negative"}>{positive ? "+" : "−"}{usdPrice(estimate.net < 0n ? -estimate.net : estimate.net)}</strong></div>
          </div>
          <p className="estimate-note">Uniswap pool fee and price impact are reflected in the exact-input quote. This estimate excludes gas cost, bridging, exchange withdrawals, and execution risk. Binance fee is a configurable estimate, not your account’s actual rate. Book received {new Date(quote!.sources.binance_received_at).toLocaleTimeString()} · Unichain block {quote!.sources.unichain_block_number}.</p>
          {snapshot && <div className="snapshot-card"><strong>Estimate snapshot · {snapshot.at}</strong><span>{snapshot.asset}/USDC · {snapshot.net >= 0n ? "potential profit" : "potential loss"} {usdPrice(snapshot.net >= 0n ? snapshot.net : -snapshot.net)}</span><small>Display only; no trade, backend record, or transaction was created.</small></div>}
          </> : <div className="quote-unavailable"><strong>{loadingQuote ? "Fetching a fresh quote…" : "Quote unavailable"}</strong><span>{quoteError || "Select an eligible asset with a configured Uniswap v4 pool and active Binance USDC market."}</span></div>}
        </section>
      </div>

      <section className="wallet-note"><strong>Optional wallet connection · WalletConnect</strong><span>Browser wallets are discovered through EIP-6963, with a legacy injected-provider fallback. WalletConnect QR is enabled with the free project ID. Connection only displays address and Unichain Sepolia network context; it does not inspect balances, request signatures, approve tokens, or send transactions. Quotes independently read Unichain Mainnet and Binance.</span></section>
      <footer className="footer-note"><span>ARBITMINT · READ-ONLY MARKET ESTIMATE</span><span>All outcomes are estimates; no CEX or DEX trade is executed.</span><a href="https://github.com/BNSx3801/arbitmint-v2" target="_blank" rel="noreferrer">View source ↗</a></footer>
    </main>
  );
}
