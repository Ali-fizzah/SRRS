/**
 * Money as the API sent it, with thousands separators: "11200.00" -> "11,200.00".
 * It stays text from start to finish; it never becomes a floating-point number (D1).
 */
export function formatMoney(amount: string): string {
  const [whole, fraction] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+$)/g, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

/** "202601" -> "2026-01" (D14 keys stay as they are everywhere else). */
export function formatPeriod(key: string): string {
  return `${key.slice(0, 4)}-${key.slice(4)}`;
}
