const countFormatter = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
})

export function formatCount(n: number): string {
  return countFormatter.format(n)
}
