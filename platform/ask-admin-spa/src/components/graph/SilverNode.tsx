/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import type { YAMLNode } from '../../api/types';

function SilverNode({ data, selected }: NodeProps<YAMLNode>) {
  return (
    <div
      className={`rounded border-2 bg-silver-light px-3 py-2 text-xs shadow-sm min-w-[160px] ${
        selected ? 'border-silver-border ring-2 ring-silver/40' : 'border-silver'
      }`}
    >
      <Handle type="source" position={Position.Top} className="!bg-silver" />
      <Handle type="target" position={Position.Bottom} className="!bg-silver" />

      <div className="flex items-center gap-1 mb-1">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-white bg-silver-border px-1 rounded">
          Silver
        </span>
        {data.module && (
          <span className="text-[9px] text-brand bg-brand/10 border border-brand/20 px-1 rounded font-medium">
            {data.module}
          </span>
        )}
      </div>
      <div className="font-semibold text-foreground truncate" title={data.name}>
        {data.name}
      </div>
      <div className="text-muted-foreground text-[10px]">
        {data.fields.length} {data.fields.length === 1 ? 'field' : 'fields'} ·{' '}
        {data.composed_of?.length ?? 0}{' '}
        {(data.composed_of?.length ?? 0) === 1 ? 'source' : 'sources'}
      </div>
    </div>
  );
}

export default memo(SilverNode);
