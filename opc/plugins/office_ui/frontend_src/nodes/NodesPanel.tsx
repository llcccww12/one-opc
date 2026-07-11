import './nodes.css'

export interface NodeCluster {
  name: string
  status: string
  region: string
  instance_type: string
  price_per_hour: number | null
  runtime_seconds: number | null
}

interface NodesPanelProps {
  nodes: { available: boolean; clusters: NodeCluster[] } | null
  onRefresh: () => void
}

export function NodesPanel({ nodes, onRefresh }: NodesPanelProps) {
  return (
    <div className="nodes-page">
      <button type="button" onClick={() => onRefresh()}>刷新</button>
      {!nodes ? null : !nodes.available ? (
        <div className="nodes-empty">未检测到本机 SkyPilot</div>
      ) : nodes.clusters.length === 0 ? (
        <div className="nodes-empty">No clusters</div>
      ) : (
        <div className="nodes-grid">
          {nodes.clusters.map(cluster => (
            <div className="nodes-card" key={cluster.name}>
              <div className="nodes-card-header">
                <span className="nodes-status-dot" data-status={cluster.status} />
                <strong>{cluster.name}</strong>
              </div>
              <div className="nodes-card-detail">{cluster.region} · {cluster.instance_type}</div>
              {cluster.price_per_hour != null && <div className="nodes-card-detail">${cluster.price_per_hour}/hr</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
