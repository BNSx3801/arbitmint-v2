export function formatBaseUnits(value: bigint, decimals: number, fractionDigits = 2): string {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const scale = 10n ** BigInt(decimals);
  const whole = absolute / scale;
  const fractional = absolute % scale;
  const fractionScale = 10n ** BigInt(fractionDigits);
  const rounded = (fractional * fractionScale + scale / 2n) / scale;
  const carry = rounded / fractionScale;
  const displayedWhole = whole + carry;
  const displayedFraction = (rounded % fractionScale).toString().padStart(fractionDigits, "0");
  return `${negative ? "−" : ""}${displayedWhole.toLocaleString("en-US")}.${displayedFraction}`;
}
