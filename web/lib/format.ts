const GB = 1024 ** 3;
const MB = 1024 ** 2;

export function humanBytes(n: number): string {
  if (n < 0) return "-" + humanBytes(-n);
  if (n >= GB) return `${(n / GB).toFixed(2)} GB`;
  if (n >= MB) return `${(n / MB).toFixed(2)} MB`;
  return `${Math.floor(n)} B`;
}

export function formatTokens(n: number): string {
  return n.toLocaleString("en-US");
}
