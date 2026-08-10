import type { CommitEntry } from '../../api/types';

interface Props {
  commits: CommitEntry[];
  fromSha: string | null;
  toSha: string | null;
  onSelectFrom(sha: string): void;
  onSelectTo(sha: string): void;
  onRestore(sha: string): void;
  hasMore: boolean;
  onLoadMore(): void;
}

function detectCommitType(message: string): 'enrichment' | 'state' | 'merge' | 'restore' | 'other' {
  if (message.startsWith('viz:')) return 'enrichment';
  if (message.startsWith('restore(')) return 'restore';
  if (message.includes('state(')) return 'state';
  if (message.includes('merge(')) return 'merge';
  return 'other';
}

const DOT_COLORS: Record<string, string> = {
  enrichment: 'bg-blue-400',
  state: 'bg-green-400',
  merge: 'bg-amber-400',
  restore: 'bg-rose-400',
  other: 'bg-gray-300',
};

const LEGEND: { type: string; label: string }[] = [
  { type: 'enrichment', label: 'edit' },
  { type: 'state', label: 'state' },
  { type: 'merge', label: 'merge' },
  { type: 'restore', label: 'restore' },
];

function formatDate(iso: string): string {
  return iso.slice(0, 10);
}

function truncate(str: string, len: number): string {
  return str.length > len ? str.slice(0, len) + '…' : str;
}

export function CommitTimeline({
  commits,
  fromSha,
  toSha,
  onSelectFrom,
  onSelectTo,
  onRestore,
  hasMore,
  onLoadMore,
}: Props) {
  if (commits.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-xs text-gray-400">
        No commits found.
      </div>
    );
  }

  return (
    <div className="flex flex-col overflow-y-auto">
      {/* Legend */}
      <div className="flex items-center gap-3 px-4 py-1.5 border-b border-gray-100 text-[10px] text-gray-400">
        {LEGEND.map((l) => (
          <span key={l.type} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-full ${DOT_COLORS[l.type]}`} />
            {l.label}
          </span>
        ))}
      </div>

      {commits.map((commit, idx) => {
        const type = detectCommitType(commit.message);
        const isFrom = commit.sha === fromSha;
        const isTo = commit.sha === toSha;
        const isLast = idx === commits.length - 1;

        return (
          <div
            key={commit.sha}
            className={`group relative flex items-start gap-3 px-4 py-2 hover:bg-gray-50 transition-colors ${
              isFrom ? 'border-l-2 border-green-500 bg-green-50' : ''
            } ${isTo ? 'border-l-2 border-blue-500 bg-blue-50' : ''}`}
          >
            {/* Timeline line */}
            <div className="flex flex-col items-center shrink-0">
              <div className={`w-2.5 h-2.5 rounded-full mt-1 ${DOT_COLORS[type]}`} />
              {!isLast && <div className="w-px flex-1 bg-gray-200 mt-1" style={{ minHeight: 16 }} />}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                  {commit.short_sha}
                </span>
                <span className="text-xs text-gray-700 truncate flex-1">
                  {truncate(commit.message, 60)}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] text-gray-400">{commit.author_email}</span>
                <span className="text-[10px] text-gray-300">•</span>
                <span className="text-[10px] text-gray-400">{formatDate(commit.timestamp)}</span>
              </div>
            </div>

            {/* Hover actions */}
            <div className="hidden group-hover:flex items-center gap-1 shrink-0">
              <button
                onClick={() => onSelectFrom(commit.sha)}
                title="Set as FROM"
                className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                  isFrom
                    ? 'border-green-500 text-green-700 bg-green-100'
                    : 'border-gray-300 text-gray-500 hover:border-green-400 hover:text-green-700'
                }`}
              >
                FROM
              </button>
              <button
                onClick={() => onSelectTo(commit.sha)}
                title="Set as TO"
                className={`text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                  isTo
                    ? 'border-blue-500 text-blue-700 bg-blue-100'
                    : 'border-gray-300 text-gray-500 hover:border-blue-400 hover:text-blue-700'
                }`}
              >
                TO
              </button>
              <button
                onClick={() => onRestore(commit.sha)}
                title="Restore to this version"
                className="text-[10px] px-1.5 py-0.5 rounded border border-gray-300 text-gray-500 hover:border-red-400 hover:text-red-600 font-medium transition-colors"
              >
                Restore
              </button>
            </div>
          </div>
        );
      })}

      {hasMore && (
        <div className="px-4 py-2">
          <button
            onClick={onLoadMore}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            Load more…
          </button>
        </div>
      )}
    </div>
  );
}
