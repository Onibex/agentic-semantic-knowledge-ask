import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type NodeTypes,
  type NodeMouseHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';
import BronzeNode from './BronzeNode';
import SilverNode from './SilverNode';
import GoldNode from './GoldNode';
import { useGraphStore } from '../../store/graphStore';

const nodeTypes: NodeTypes = {
  bronzeNode: BronzeNode,
  silverNode: SilverNode,
  goldNode: GoldNode,
};

/** MIME type carried by a Knowledge-rail drag (domain canvas, §03). */
export const ASK_ENTITY_DND = 'application/x-ask-entity';

interface YAMLGraphProps {
  /** When set, the canvas becomes a drop target — dropping a Knowledge item
   *  calls this with the dragged entity id (domain canvas adds it to the BD). */
  onDropEntity?: (entityId: string) => void;
}

export function YAMLGraph({ onDropEntity }: YAMLGraphProps = {}) {
  const { rfNodes, rfEdges, selectedNodeId, selectNode, searchQuery, searchResults, focusNodeId } = useGraphStore();

  const onNodeClick: NodeMouseHandler = (_evt, node) => {
    selectNode(node.id === selectedNodeId ? null : node.id);
  };

  const displayNodes = searchQuery
    ? rfNodes.map((n) => ({
        ...n,
        style: {
          ...n.style,
          opacity: searchResults.has(n.id) ? 1 : 0.15,
        },
      }))
    : rfNodes;

  const flow = (
    <ReactFlow
      key={focusNodeId ?? 'all'}
      nodes={displayNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.2}
      maxZoom={2}
      attributionPosition="bottom-right"
    >
      <Background gap={20} size={1} color="#e2e8f0" />
      <Controls />
      <MiniMap
        nodeColor={(n) => {
          if (n.type === 'bronzeNode') return '#4a7ab5';
          if (n.type === 'silverNode') return '#718096';
          return '#d69e2e';
        }}
        maskColor="rgba(248,250,252,0.7)"
      />
    </ReactFlow>
  );

  // GraphPage uses the bare flow (current behaviour). The domain canvas passes
  // onDropEntity → wrap in a drop target so a Knowledge item dragged onto the
  // pane is added to the domain. Position is irrelevant (auto-layout relays out
  // on the refetch), so we only read the dragged id.
  if (!onDropEntity) return flow;

  return (
    <div
      className="w-full h-full"
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
      }}
      onDrop={(e) => {
        e.preventDefault();
        const id = e.dataTransfer.getData(ASK_ENTITY_DND);
        if (id) onDropEntity(id);
      }}
    >
      {flow}
    </div>
  );
}
