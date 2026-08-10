import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import type { YAMLNode } from '../../api/types';

function BronzeNode({ data, selected }: NodeProps<YAMLNode>) {
  return (
    <div
      className={`rounded border-2 bg-bronze-light px-3 py-2 text-xs shadow-sm min-w-[140px] ${
        selected ? 'border-bronze-border ring-2 ring-bronze/40' : 'border-bronze'
      }`}
    >
      <Handle type="source" position={Position.Top} className="!bg-bronze" />
      <Handle type="target" position={Position.Bottom} className="!bg-bronze" />

      <div className="flex items-center gap-1 mb-1">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-white bg-bronze-border px-1 rounded">
          Bronze
        </span>
      </div>
      <div className="font-semibold text-foreground truncate" title={data.name}>
        {data.alias || data.name}
      </div>
      {/* Technical SAP table name (e.g. VBAK) — SAP users locate entities by it.
          Only when an alias is shown above, else it would just duplicate it. */}
      {data.alias && data.alias !== data.name && (
        <div className="font-mono text-[10px] text-bronze-border/80 truncate" title={data.name}>
          {data.name}
        </div>
      )}
      <div className="text-muted-foreground text-[10px]">
        {data.fields.length} {data.fields.length === 1 ? 'field' : 'fields'}
      </div>
    </div>
  );
}

export default memo(BronzeNode);
