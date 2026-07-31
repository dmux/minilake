"""MCP tools for Clusters (/api/2.1/clusters).

Clusters are a state machine only — there is no Spark compute behind them. Real Spark
execution happens through Jobs (see run_python_script). These tools exist so client code
that creates and polls clusters can be exercised.
"""

from typing import Any, Optional

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.1/clusters"

_NO_COMPUTE_NOTE = (
    "Note: minilake clusters are a state machine with no Spark compute behind them. "
    "To actually execute Spark code, use run_python_script."
)


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def create_cluster(
        cluster_name: str,
        spark_version: str = "13.3.x-scala2.12",
        node_type_id: str = "Standard_DS3_v2",
        num_workers: Optional[int] = 1,
    ) -> dict[str, Any]:
        """Create a cluster. Transitions PENDING -> RUNNING after a short real delay.

        No Spark compute is attached — this only drives the lifecycle state machine.
        """
        body = await client.post(
            f"{_PREFIX}/create",
            json={
                "cluster_name": cluster_name,
                "spark_version": spark_version,
                "node_type_id": node_type_id,
                "num_workers": num_workers,
            },
        )
        return {**body, "note": _NO_COMPUTE_NOTE}

    @mcp.tool()
    async def list_clusters() -> dict[str, Any]:
        """List all clusters and their states."""
        return await client.get(f"{_PREFIX}/list")

    @mcp.tool()
    async def get_cluster(cluster_id: str) -> dict[str, Any]:
        """Get one cluster's details and current state."""
        return await client.get(f"{_PREFIX}/get", params={"cluster_id": cluster_id})

    @mcp.tool()
    async def start_cluster(cluster_id: str) -> dict[str, Any]:
        """Start a terminated cluster (PENDING -> RUNNING)."""
        return await client.post(f"{_PREFIX}/start", json={"cluster_id": cluster_id})

    @mcp.tool()
    async def terminate_cluster(cluster_id: str) -> dict[str, Any]:
        """Terminate a cluster (TERMINATING -> TERMINATED). The record is kept."""
        return await client.post(f"{_PREFIX}/delete", json={"cluster_id": cluster_id})
