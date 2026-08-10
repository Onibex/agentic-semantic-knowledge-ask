import dagre from 'dagre';
import { MarkerType } from 'reactflow';
import type { Node, Edge } from 'reactflow';
import type { YAMLNode } from '../../api/types';

const NODE_WIDTH: Record<string, number> = { bronze: 160, silver: 200, gold: 180 };
const NODE_HEIGHT: Record<string, number> = { bronze: 80, silver: 100, gold: 90 };

// Lineage graph only: edges express "depends on / is composed of", never SQL join
// topology. Join conditions (INNER/LEFT) live in the entity's detail panel.
//   composed edge  → Silver/Gold → its Bronze tables (ordered by join sequence)
//   lineage edge   → Silver→Silver, Gold→Silver/Gold (from `relationships`)
// Ranks are derived from the edges (dagre), so chains like
// gold→gold→silver→silver→bronze produce as many levels as the data has.
const COMPOSED_STYLE = { stroke: '#94a3b8', strokeWidth: 1.5 };
const LINEAGE_STYLE = { stroke: '#7c3aed', strokeWidth: 1.6 };

export interface DerivedEdge {
  source: string;
  target: string;
  kind: 'composed' | 'lineage';
  label?: string;
}

function pushTo(m: Map<string, string[]>, key: string, value: string) {
  const arr = m.get(key);
  if (arr) arr.push(value);
  else m.set(key, [value]);
}

/**
 * Derive the lineage edges for a set of nodes (deduped, one per pair). Shared by
 * the layout, the fan-in counts and the focus-mode reachability so all three
 * agree on what "an edge" is.
 */
export function deriveEdges(nodes: YAMLNode[]): DerivedEdge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const byTable = new Map<string, YAMLNode>();
  for (const n of nodes) {
    if (n.name) byTable.set(n.name.toLowerCase(), n);
    if (n.alias) byTable.set(n.alias.toLowerCase(), n);
  }
  const resolve = (ref: string): YAMLNode | undefined =>
    byId.get(ref) ?? byTable.get(ref.toLowerCase());

  // Sequence of a Bronze within a Silver's join_graph (for sibling ordering).
  const bronzeSeq = (silver: YAMLNode, bronze: YAMLNode): number => {
    const nm = (bronze.name ?? '').toLowerCase();
    const al = (bronze.alias ?? '').toLowerCase();
    for (const j of silver.join_graph ?? []) {
      const rt = (j.right_table ?? '').toLowerCase();
      if (rt === nm || rt === al) return j.sequence ?? 999;
    }
    return 0; // anchor / not referenced as a right_table
  };

  const seen = new Set<string>();
  const out: DerivedEdge[] = [];
  const push = (source: string, target: string, kind: 'composed' | 'lineage', label?: string) => {
    if (source === target) return;
    const key = `${source}->${target}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ source, target, kind, label });
  };

  for (const n of nodes) {
    if (n.layer !== 'silver' && n.layer !== 'gold') continue;

    const composed = (n.composed_of ?? []).map(resolve).filter((t): t is YAMLNode => !!t);
    const bronzes = composed
      .filter((t) => t.layer === 'bronze')
      .sort((a, b) => bronzeSeq(n, a) - bronzeSeq(n, b));
    for (const b of bronzes) push(n.id, b.id, 'composed');
    for (const o of composed.filter((t) => t.layer !== 'bronze')) push(n.id, o.id, 'lineage');

    for (const rel of n.relationships ?? []) {
      const t = resolve(rel.target_entity);
      if (t && (t.layer === 'silver' || t.layer === 'gold')) {
        push(n.id, t.id, 'lineage', rel.semantic_label ?? undefined);
      }
    }
  }
  return out;
}

/** Fan-in count per node id (how many entities reference it) — used to spot hubs. */
export function computeRefCounts(nodes: YAMLNode[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const e of deriveEdges(nodes)) {
    counts[e.target] = (counts[e.target] ?? 0) + 1;
  }
  return counts;
}

/**
 * The full lineage of a focused node: itself + everything it is built from
 * (descendants) + everything that consumes it (ancestors), transitively.
 */
export function lineageNodeIds(nodes: YAMLNode[], focusId: string): Set<string> {
  const edges = deriveEdges(nodes);
  const down = new Map<string, string[]>(); // source → targets (depends on)
  const up = new Map<string, string[]>(); //   target → sources (consumed by)
  for (const e of edges) {
    pushTo(down, e.source, e.target);
    pushTo(up, e.target, e.source);
  }

  const result = new Set<string>([focusId]);
  const walk = (adj: Map<string, string[]>) => {
    const stack = [focusId];
    while (stack.length) {
      const n = stack.pop()!;
      for (const m of adj.get(n) ?? []) {
        if (!result.has(m)) {
          result.add(m);
          stack.push(m);
        }
      }
    }
  };
  walk(down);
  walk(up);
  return result;
}

export function buildLayout(nodes: YAMLNode[]): { rfNodes: Node[]; rfEdges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'BT', nodesep: 60, ranksep: 110, marginx: 40, marginy: 40 });

  for (const n of nodes) {
    g.setNode(n.id, {
      width: NODE_WIDTH[n.layer] ?? 180,
      height: NODE_HEIGHT[n.layer] ?? 90,
    });
  }

  const present = new Set(nodes.map((n) => n.id));
  const rfEdges: Edge[] = [];
  for (const e of deriveEdges(nodes)) {
    if (!present.has(e.source) || !present.has(e.target)) continue;
    g.setEdge(e.source, e.target);
    const color = e.kind === 'composed' ? '#94a3b8' : '#7c3aed';
    rfEdges.push({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      label: e.label,
      style: e.kind === 'composed' ? COMPOSED_STYLE : LINEAGE_STYLE,
      labelStyle: { fontSize: 10, fill: '#6d28d9', fontWeight: 500 },
      labelBgStyle: { fill: '#f5f3ff', fillOpacity: 0.9 },
      labelBgPadding: [4, 2],
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
    });
  }

  dagre.layout(g);

  const rfNodes: Node[] = nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      type: `${n.layer}Node`,
      position: {
        x: pos.x - (NODE_WIDTH[n.layer] ?? 180) / 2,
        y: pos.y - (NODE_HEIGHT[n.layer] ?? 90) / 2,
      },
      data: n,
    };
  });

  return { rfNodes, rfEdges };
}
