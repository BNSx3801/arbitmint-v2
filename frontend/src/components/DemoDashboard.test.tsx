import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DemoDashboard } from "./DemoDashboard";

describe("DemoDashboard market quote disclosure", () => {
  it("starts unavailable until live read-only sources return a quote", () => {
    const html = renderToStaticMarkup(createElement(DemoDashboard));

    expect(html).toContain("Read-only market estimate.");
    expect(html).toContain("Quote unavailable");
    expect(html).not.toContain("Prices below are generated locally");
    expect(html).not.toContain("Simulated CEX sale value");
    expect(html).toContain("WalletConnect QR");
  });
});
