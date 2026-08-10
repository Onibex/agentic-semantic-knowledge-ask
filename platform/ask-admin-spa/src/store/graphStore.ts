import { create } from 'zustand';
import type { Node, Edge } from 'reactflow';
import { listYamls, listScopedYamls, getYaml, searchYamls, type ListYamlsOptions } from '../api/client';
import type { EntityRole, YAMLLayer, YAMLNode } from '../api/types';
import { buildLayout, computeRefCounts, lineageNodeIds } from '../components/graph/layout';

const ALL_ROLES: EntityRole[] = ['fact', 'dimension', 'reference'];

/**
 * What the graph is scoped to. A bare string is a workspace id/slug (back-compat
 * with existing callers); an object can scope to a single Business Domain (the
 * domain canvas, design-spec §03). `businessDomain` is narrower and wins.
 */
export type GraphScope =
  | string
  | { workspace?: string | null; businessDomain?: string | null };

function scopeToOpts(scope?: GraphScope | null): ListYamlsOptions | undefined {
  if (!scope) return undefined;
  if (typeof scope === 'string') return { workspace: scope };
  if (scope.businessDomain) return { businessDomain: scope.businessDomain };
  if (scope.workspace) return { workspace: scope.workspace };
  return undefined;
}

interface Filters {
  layers: Set<YAMLLayer>;
  modules: Set<string>;
  roles: Set<string>; // entity_role values visible by default (Silver/Gold)
}

interface ViewState {
  rfNodes: Node[];
  rfEdges: Edge[];
  visibleIds: Set<string>;
}

interface GraphStore {
  rawNodes: YAMLNode[];
  rfNodes: Node[];
  rfEdges: Edge[];
  allModules: string[];
  refCounts: Record<string, number>;
  filters: Filters;
  /** Per-entity explicit show(true)/hide(false) — overrides the role/layer default. */
  overrides: Map<string, boolean>;
  visibleIds: Set<string>;
  focusNodeId: string | null;
  selectedNodeId: string | null;
  selectedNode: YAMLNode | null;
  loading: boolean;
  error: string | null;
  searchQuery: string;
  searchResults: Set<string>;

  /**
   * Load the catalogue from the backend, scoped to a workspace OR a single
   * Business Domain (the domain canvas, §03). A bare string is a workspace
   * id/slug (back-compat); pass `{ businessDomain }` to scope to one domain.
   * The server returns that scope's DPs + one-hop neighbors (composed_of
   * bronzes + relationship targets). Omit the arg to load everything.
   */
  fetchAll(scope?: GraphScope | null): Promise<void>;
  ensureLoaded(scope?: GraphScope | null): Promise<void>;
  /** Drop the loaded catalogue + selection — used when the active workspace changes. */
  reset(): void;
  replaceNode(updated: YAMLNode): void;
  mergeNodes(updated: YAMLNode[]): void;
  removeNode(id: string): void;
  removeNodes(ids: string[]): void;
  revealNode(id: string): void;
  toggleLayer(layer: YAMLLayer): void;
  toggleModule(module: string): void;
  toggleRole(role: string): void;
  toggleEntity(id: string): void;
  resetView(scope: 'main' | 'all'): void;
  setFocus(id: string | null): void;
  selectNode(id: string | null): void;
  setSearch(q: string): Promise<void>;
  clearSearch(): void;
}

function defaultFilters(scope: 'main' | 'all' = 'main'): Filters {
  return scope === 'all'
    ? { layers: new Set<YAMLLayer>(['bronze', 'silver', 'gold']), modules: new Set(), roles: new Set(ALL_ROLES) }
    : { layers: new Set<YAMLLayer>(['silver', 'gold']), modules: new Set(), roles: new Set(['fact']) };
}

/** Compute the visible node set + laid-out graph from the current view state. */
function computeView(
  nodes: YAMLNode[],
  filters: Filters,
  overrides: Map<string, boolean>,
  focusNodeId: string | null,
): ViewState {
  let visible: YAMLNode[];

  if (focusNodeId) {
    const ids = lineageNodeIds(nodes, focusNodeId);
    visible = nodes.filter((n) => ids.has(n.id));
  } else {
    const moduleOk = (n: YAMLNode) =>
      !(filters.modules.size > 0 && n.module && !filters.modules.has(n.module));
    const roleOf = (n: YAMLNode) => (n.entity_role as string) ?? 'fact';

    // Silver/Gold visibility: role + layer + module, with per-entity override.
    const baseSG = (n: YAMLNode) =>
      filters.layers.has(n.layer) && filters.roles.has(roleOf(n)) && moduleOk(n);
    const visibleSG = nodes.filter(
      (n) =>
        (n.layer === 'silver' || n.layer === 'gold') &&
        (overrides.has(n.id) ? overrides.get(n.id)! : baseSG(n)),
    );

    // Bronze tables referenced by a visible Silver/Gold (so we don't surface
    // orphan bronzes of hidden dimensions).
    const referenced = new Set<string>();
    for (const sg of visibleSG) for (const c of sg.composed_of ?? []) referenced.add(c);

    const visibleBronze = nodes.filter((n) => {
      if (n.layer !== 'bronze') return false;
      const base = filters.layers.has('bronze') && referenced.has(n.id) && moduleOk(n);
      return overrides.has(n.id) ? overrides.get(n.id)! : base;
    });

    visible = [...visibleSG, ...visibleBronze];
  }

  const { rfNodes, rfEdges } = buildLayout(visible);
  return { rfNodes, rfEdges, visibleIds: new Set(visible.map((n) => n.id)) };
}

export const useGraphStore = create<GraphStore>((set, get) => ({
  rawNodes: [],
  rfNodes: [],
  rfEdges: [],
  allModules: [],
  refCounts: {},
  filters: defaultFilters('main'),
  overrides: new Map(),
  visibleIds: new Set<string>(),
  focusNodeId: null,
  selectedNodeId: null,
  selectedNode: null,
  loading: false,
  error: null,
  searchQuery: '',
  searchResults: new Set<string>(),

  async fetchAll(scope?: GraphScope | null) {
    set({ loading: true, error: null });
    try {
      const opts = scopeToOpts(scope);
      // Scoped load (workspace OR domain): one request returns every in-scope
      // full node in a single backend pass — avoids the old listYamls + N x
      // getYaml storm (each getYaml rglobbed the whole workspace, O(N x files)).
      // Unscoped (load everything) keeps the legacy summaries + per-id path.
      const nodes: YAMLNode[] =
        opts && (opts.businessDomain || opts.workspace)
          ? await listScopedYamls(opts)
          : await Promise.all((await listYamls(opts)).map((s) => getYaml(s.id)));
      const allModules = [...new Set(nodes.flatMap((n) => (n.module ? [n.module] : [])))].sort();
      const filters = defaultFilters('main');
      const overrides = new Map<string, boolean>();
      const view = computeView(nodes, filters, overrides, null);
      set({
        rawNodes: nodes,
        allModules,
        refCounts: computeRefCounts(nodes),
        filters,
        overrides,
        focusNodeId: null,
        loading: false,
        ...view,
      });
    } catch (err) {
      set({ loading: false, error: String(err) });
    }
  },

  async ensureLoaded(scope?: GraphScope | null) {
    const { rawNodes, loading } = get();
    if (loading || rawNodes.length > 0) return;
    await get().fetchAll(scope);
  },

  reset() {
    set({
      rawNodes: [],
      rfNodes: [],
      rfEdges: [],
      visibleIds: new Set<string>(),
      allModules: [],
      refCounts: {},
      selectedNodeId: null,
      selectedNode: null,
      focusNodeId: null,
      filters: defaultFilters('main'),
      overrides: new Map<string, boolean>(),
      searchQuery: '',
      searchResults: new Set<string>(),
      error: null,
    });
  },

  // Swap a single updated node in-place (after a save / state change) instead of
  // refetching the whole catalog — avoids ~N HTTP round trips + O(N^2) backend scan.
  replaceNode(updated: YAMLNode) {
    const { rawNodes, filters, overrides, focusNodeId, selectedNodeId } = get();
    const exists = rawNodes.some((n) => n.id === updated.id);
    const nodes = exists
      ? rawNodes.map((n) => (n.id === updated.id ? updated : n))
      : [...rawNodes, updated];
    set({
      rawNodes: nodes,
      refCounts: computeRefCounts(nodes),
      selectedNode: selectedNodeId === updated.id ? updated : get().selectedNode,
      ...computeView(nodes, filters, overrides, focusNodeId),
    });
  },

  // Splice several nodes in at once (replace-or-append), recomputing the view a
  // single time — used when a drop pulls in an entity AND its composed_of bronzes
  // together. Preserves filters / overrides / focus, no refetch. A Map keyed by
  // id de-dups against what's already loaded (a shared bronze keeps its slot).
  mergeNodes(updated: YAMLNode[]) {
    if (updated.length === 0) return;
    const { rawNodes, filters, overrides, focusNodeId, selectedNodeId } = get();
    const byId = new Map(rawNodes.map((n) => [n.id, n]));
    for (const u of updated) byId.set(u.id, u);
    const nodes = [...byId.values()];
    set({
      rawNodes: nodes,
      refCounts: computeRefCounts(nodes),
      selectedNode: selectedNodeId ? byId.get(selectedNodeId) ?? get().selectedNode : get().selectedNode,
      ...computeView(nodes, filters, overrides, focusNodeId),
    });
  },

  // Drop a node in-place (after removing it from a domain) — preserves the
  // current filters / overrides / focus and does NOT refetch, so the user's
  // view is undisturbed. Clears selection/focus if they pointed at the node.
  removeNode(id: string) {
    const { rawNodes, filters, overrides, focusNodeId, selectedNodeId } = get();
    const nodes = rawNodes.filter((n) => n.id !== id);
    const nextOverrides = new Map(overrides);
    nextOverrides.delete(id);
    const nextFocus = focusNodeId === id ? null : focusNodeId;
    set({
      rawNodes: nodes,
      refCounts: computeRefCounts(nodes),
      overrides: nextOverrides,
      focusNodeId: nextFocus,
      selectedNodeId: selectedNodeId === id ? null : selectedNodeId,
      selectedNode: selectedNodeId === id ? null : get().selectedNode,
      ...computeView(nodes, filters, nextOverrides, nextFocus),
    });
  },

  // Drop several nodes at once (entity + its now-orphaned composed_of bronzes)
  // in one recompute. Same in-place contract as removeNode: preserves filters /
  // overrides / focus, clears selection/focus if they pointed at a removed node.
  removeNodes(ids: string[]) {
    if (ids.length === 0) return;
    const idSet = new Set(ids);
    const { rawNodes, filters, overrides, focusNodeId, selectedNodeId } = get();
    const nodes = rawNodes.filter((n) => !idSet.has(n.id));
    const nextOverrides = new Map(overrides);
    for (const id of ids) nextOverrides.delete(id);
    const nextFocus = focusNodeId && idSet.has(focusNodeId) ? null : focusNodeId;
    const selCleared = !!selectedNodeId && idSet.has(selectedNodeId);
    set({
      rawNodes: nodes,
      refCounts: computeRefCounts(nodes),
      overrides: nextOverrides,
      focusNodeId: nextFocus,
      selectedNodeId: selCleared ? null : selectedNodeId,
      selectedNode: selCleared ? null : get().selectedNode,
      ...computeView(nodes, filters, nextOverrides, nextFocus),
    });
  },

  // Force a node visible regardless of the current role/layer filters — used
  // right after adding a DP to a domain so the user SEES what they just added
  // (an explicit per-entity override, same mechanism as toggleEntity).
  revealNode(id: string) {
    const { rawNodes, filters, overrides, focusNodeId } = get();
    const next = new Map(overrides);
    next.set(id, true);
    set({ overrides: next, ...computeView(rawNodes, filters, next, focusNodeId) });
  },

  toggleLayer(layer: YAMLLayer) {
    const { rawNodes, filters, overrides, focusNodeId } = get();
    const layers = new Set(filters.layers);
    if (layers.has(layer)) layers.delete(layer);
    else layers.add(layer);
    const next = { ...filters, layers };
    // The layer checkbox is authoritative for its layer: drop per-entity
    // overrides (e.g. a just-revealed node) for that layer so toggling shows /
    // hides ALL of them, not just the un-pinned ones.
    const nextOverrides = new Map(overrides);
    for (const n of rawNodes) if (n.layer === layer) nextOverrides.delete(n.id);
    set({ filters: next, overrides: nextOverrides, ...computeView(rawNodes, next, nextOverrides, focusNodeId) });
  },

  toggleModule(module: string) {
    const { rawNodes, filters, overrides, focusNodeId } = get();
    const modules = new Set(filters.modules);
    if (modules.has(module)) modules.delete(module);
    else modules.add(module);
    const next = { ...filters, modules };
    set({ filters: next, ...computeView(rawNodes, next, overrides, focusNodeId) });
  },

  toggleRole(role: string) {
    const { rawNodes, filters, overrides, focusNodeId } = get();
    const roles = new Set(filters.roles);
    if (roles.has(role)) roles.delete(role);
    else roles.add(role);
    const next = { ...filters, roles };
    // The role checkbox is authoritative for its role: drop per-entity overrides
    // (e.g. a dimension just dragged in + revealed) for entities of that role,
    // so toggling Dimension shows / hides ALL dimensions — not just the
    // un-pinned ones. (Fixes: a revealed dimension stayed visible after
    // unchecking Dimension because its override beat the role filter.)
    const roleOf = (n: YAMLNode) => (n.entity_role as string) ?? 'fact';
    const nextOverrides = new Map(overrides);
    for (const n of rawNodes) if (roleOf(n) === role) nextOverrides.delete(n.id);
    set({ filters: next, overrides: nextOverrides, ...computeView(rawNodes, next, nextOverrides, focusNodeId) });
  },

  toggleEntity(id: string) {
    const { rawNodes, filters, overrides, focusNodeId, visibleIds } = get();
    const next = new Map(overrides);
    // Flip current effective visibility into an explicit override.
    next.set(id, !visibleIds.has(id));
    set({ overrides: next, ...computeView(rawNodes, filters, next, focusNodeId) });
  },

  resetView(scope: 'main' | 'all') {
    const { rawNodes, focusNodeId } = get();
    const filters = defaultFilters(scope);
    const overrides = new Map<string, boolean>();
    set({ filters, overrides, ...computeView(rawNodes, filters, overrides, focusNodeId) });
  },

  setFocus(id: string | null) {
    const { rawNodes, filters, overrides } = get();
    set({ focusNodeId: id, ...computeView(rawNodes, filters, overrides, id) });
  },

  selectNode(id: string | null) {
    const node = id ? get().rawNodes.find((n) => n.id === id) ?? null : null;
    set({ selectedNodeId: id, selectedNode: node });
  },

  async setSearch(q: string) {
    if (!q) {
      set({ searchQuery: '', searchResults: new Set<string>() });
      return;
    }
    try {
      const results = await searchYamls(q);
      set({ searchQuery: q, searchResults: new Set(results.map((r) => r.id)) });
    } catch {
      set({ searchQuery: q, searchResults: new Set<string>() });
    }
  },

  clearSearch() {
    set({ searchQuery: '', searchResults: new Set<string>() });
  },
}));
