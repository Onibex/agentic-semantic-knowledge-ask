import type { DataProductStatus } from '@/api/types'

/**
 * DataProduct lifecycle status pill (UX_CHANGES audit §5.4 / CH-1).
 *
 *   In Review → amber (working definition differs from what's deployed to dev)
 *   Released  → green (working == dev)
 */
export function StatusPill({ status, className = '' }: { status: DataProductStatus; className?: string }) {
  const isReleased = status === 'Released'
  const color = isReleased
    ? 'bg-green-100 text-green-700'
    : 'bg-amber-100 text-amber-700'
  const dot = isReleased ? 'bg-green-500' : 'bg-amber-500'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ${color} ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {status}
    </span>
  )
}

/**
 * Compact released/in-review counts for a group of DataProducts (workspace-home
 * "status dots"). Renders nothing when there are no tracked DPs.
 */
export function StatusSummary({
  released,
  inReview,
  className = '',
}: {
  released: number
  inReview: number
  className?: string
}) {
  if (released === 0 && inReview === 0) return null
  return (
    <span className={`inline-flex items-center gap-2 text-[11px] font-medium ${className}`}>
      {released > 0 && (
        <span className="inline-flex items-center gap-1 text-green-700">
          <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
          {released} released
        </span>
      )}
      {inReview > 0 && (
        <span className="inline-flex items-center gap-1 text-amber-700">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          {inReview} in review
        </span>
      )}
    </span>
  )
}
