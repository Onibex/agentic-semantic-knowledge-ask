interface Props {
  unifiedDiff: string;
  fromSha: string;
  toSha: string;
}

function classifyLine(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return 'bg-gray-100 text-gray-500';
  }
  if (line.startsWith('+')) {
    return 'bg-green-50 text-green-800';
  }
  if (line.startsWith('-')) {
    return 'bg-red-50 text-red-800';
  }
  if (line.startsWith('@@')) {
    return 'bg-blue-50 text-blue-600 italic';
  }
  return 'bg-white text-gray-700';
}

export function SimpleDiffViewer({ unifiedDiff, fromSha, toSha }: Props) {
  const lines = unifiedDiff.split('\n');

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-200 shrink-0">
        <span className="text-xs font-medium text-gray-600">
          Changes from{' '}
          <span className="font-mono bg-gray-100 px-1 rounded">{fromSha.slice(0, 7)}</span>
          {' '}
          <span className="text-gray-400">→</span>
          {' '}
          <span className="font-mono bg-gray-100 px-1 rounded">{toSha.slice(0, 7)}</span>
        </span>
      </div>
      <div className="flex-1 overflow-auto">
        <pre className="font-mono text-xs leading-5 min-w-0">
          {lines.map((line, i) => (
            <div key={i} className={`px-3 ${classifyLine(line)}`}>
              {line || ' '}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
