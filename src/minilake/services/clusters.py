"""Clusters API endpoints.

Real, lightweight state-machine emulation (PENDING -> RUNNING,
TERMINATING -> TERMINATED, ...) with configurable delays, so local
Terraform plans / SDK scripts that create a cluster and poll for RUNNING
(as the real databricks-sdk's `create().result()` waiter does) exercise
real polling logic instead of getting an instant, faked answer.

No real Spark compute is started here (that's Jobs' job, via
docker_executor's sibling-container execution) — this is metadata + state
transitions only, matching the project's documented scope cut for Clusters.
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Query

from minilake.config import settings
from minilake.errors import DatabricksError
from minilake.models.clusters import (
    ChangeClusterOwnerRequest,
    ClusterEventsRequest,
    ClusterEventsResponse,
    ClusterIdRequest,
    ClusterInfo,
    CreateClusterRequest,
    CreateClusterResponse,
    EditClusterRequest,
    GetSparkVersionsResponse,
    ListClustersResponse,
    ListNodeTypesResponse,
    ListZonesResponse,
    NodeType,
    ResizeClusterRequest,
    RestartClusterRequest,
    SparkVersion,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.1/clusters", tags=["clusters"])

_state: Dict[str, Any] = {"clusters": {}}


def _get_or_404(cluster_id: str) -> dict:
    cluster = _state["clusters"].get(cluster_id)
    if cluster is None:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Cluster '{cluster_id}' not found",
            status_code=404,
        )
    return cluster


async def _transition(cluster_id: str, delay_seconds: float, target_state: str) -> None:
    """Background transition: flips a cluster's state after a real delay."""
    await asyncio.sleep(delay_seconds)
    cluster = _state["clusters"].get(cluster_id)
    if cluster is None:
        return
    cluster["state"] = target_state
    cluster["state_message"] = ""
    if target_state == "RUNNING":
        cluster["start_time"] = int(time.time() * 1000)
    elif target_state == "TERMINATED":
        cluster["terminated_time"] = int(time.time() * 1000)
    logger.info(f"Cluster {cluster_id} transitioned to {target_state}")


def _to_info(cluster: dict) -> ClusterInfo:
    return ClusterInfo(**cluster)


@router.post("/create", response_model=CreateClusterResponse)
async def create_cluster(req: CreateClusterRequest) -> CreateClusterResponse:
    """Create a cluster. Starts in PENDING, transitions to RUNNING for real
    after MINILAKE_CLUSTER_START_DELAY seconds."""
    cluster_id = str(uuid.uuid4())[:8]
    cluster = {
        "cluster_id": cluster_id,
        "cluster_name": req.cluster_name,
        "spark_version": req.spark_version,
        "node_type_id": req.node_type_id,
        "driver_node_type_id": req.driver_node_type_id or req.node_type_id,
        "num_workers": req.num_workers,
        "autotermination_minutes": req.autotermination_minutes,
        "spark_conf": req.spark_conf,
        "spark_env_vars": req.spark_env_vars,
        "custom_tags": req.custom_tags,
        "autoscale": req.autoscale,
        "state": "PENDING",
        "state_message": "Starting cluster",
        "creator_user_name": "minilake-user",
        "start_time": int(time.time() * 1000),
        "terminated_time": None,
        "last_restarted_time": None,
        "default_tags": {},
    }
    _state["clusters"][cluster_id] = cluster
    asyncio.create_task(_transition(cluster_id, settings.cluster_start_delay_seconds, "RUNNING"))
    logger.info(f"Created cluster: {cluster_id} ({req.cluster_name})")
    return CreateClusterResponse(cluster_id=cluster_id)


@router.post("/edit", response_model=ClusterInfo)
async def edit_cluster(req: EditClusterRequest) -> ClusterInfo:
    """Edit a cluster's config in place."""
    cluster = _get_or_404(req.cluster_id)
    cluster["cluster_name"] = req.cluster_name
    cluster["spark_version"] = req.spark_version
    cluster["node_type_id"] = req.node_type_id
    cluster["driver_node_type_id"] = req.driver_node_type_id or req.node_type_id
    cluster["num_workers"] = req.num_workers
    cluster["autotermination_minutes"] = req.autotermination_minutes
    cluster["spark_conf"] = req.spark_conf
    cluster["spark_env_vars"] = req.spark_env_vars
    cluster["custom_tags"] = req.custom_tags
    cluster["autoscale"] = req.autoscale
    return _to_info(cluster)


@router.post("/start", response_model=ClusterInfo)
async def start_cluster(req: ClusterIdRequest) -> ClusterInfo:
    """Start a terminated cluster. No-op if already RUNNING/PENDING."""
    cluster = _get_or_404(req.cluster_id)
    if cluster["state"] in ("RUNNING", "PENDING"):
        return _to_info(cluster)
    cluster["state"] = "PENDING"
    cluster["state_message"] = "Starting cluster"
    cluster["terminated_time"] = None
    asyncio.create_task(_transition(req.cluster_id, settings.cluster_start_delay_seconds, "RUNNING"))
    return _to_info(cluster)


@router.post("/delete", response_model=ClusterInfo)
async def terminate_cluster(req: ClusterIdRequest) -> ClusterInfo:
    """Terminate a cluster (kept in state for history, like real Databricks)."""
    cluster = _get_or_404(req.cluster_id)
    if cluster["state"] in ("TERMINATED", "TERMINATING"):
        return _to_info(cluster)
    cluster["state"] = "TERMINATING"
    cluster["state_message"] = "Terminating cluster"
    asyncio.create_task(_transition(req.cluster_id, settings.cluster_terminate_delay_seconds, "TERMINATED"))
    return _to_info(cluster)


@router.post("/permanent-delete")
async def permanent_delete_cluster(req: ClusterIdRequest) -> dict:
    """Permanently remove a cluster's record (unlike /delete, no history kept)."""
    _get_or_404(req.cluster_id)
    del _state["clusters"][req.cluster_id]
    return {}


@router.post("/restart", response_model=ClusterInfo)
async def restart_cluster(req: RestartClusterRequest) -> ClusterInfo:
    """Restart a running cluster: RESTARTING -> RUNNING after the start delay."""
    cluster = _get_or_404(req.cluster_id)
    cluster["state"] = "RESTARTING"
    cluster["state_message"] = "Restarting cluster"
    cluster["last_restarted_time"] = int(time.time() * 1000)
    asyncio.create_task(_transition(req.cluster_id, settings.cluster_start_delay_seconds, "RUNNING"))
    return _to_info(cluster)


@router.post("/resize", response_model=ClusterInfo)
async def resize_cluster(req: ResizeClusterRequest) -> ClusterInfo:
    """Resize a cluster's worker count: RESIZING -> RUNNING after the start delay."""
    cluster = _get_or_404(req.cluster_id)
    if req.num_workers is not None:
        cluster["num_workers"] = req.num_workers
    if req.autoscale is not None:
        cluster["autoscale"] = req.autoscale
    cluster["state"] = "RESIZING"
    cluster["state_message"] = "Resizing cluster"
    asyncio.create_task(_transition(req.cluster_id, settings.cluster_start_delay_seconds, "RUNNING"))
    return _to_info(cluster)


@router.post("/change-owner")
async def change_owner(req: ChangeClusterOwnerRequest) -> dict:
    """Change a cluster's owner."""
    cluster = _get_or_404(req.cluster_id)
    cluster["creator_user_name"] = req.owner_username
    return {}


@router.get("/get", response_model=ClusterInfo)
async def get_cluster(cluster_id: str = Query(...)) -> ClusterInfo:
    """Get a cluster by ID."""
    return _to_info(_get_or_404(cluster_id))


@router.get("/list", response_model=ListClustersResponse)
async def list_clusters() -> ListClustersResponse:
    """List all clusters (active and terminated, no 30-day pruning applied)."""
    return ListClustersResponse(clusters=[_to_info(c) for c in _state["clusters"].values()])


@router.post("/events", response_model=ClusterEventsResponse)
async def cluster_events(req: ClusterEventsRequest) -> ClusterEventsResponse:
    """No real event log is kept; returns an empty (but valid) event list."""
    _get_or_404(req.cluster_id)
    return ClusterEventsResponse(events=[])


@router.get("/list-node-types", response_model=ListNodeTypesResponse)
async def list_node_types() -> ListNodeTypesResponse:
    """Static, plausible node type catalog (no real cloud provider behind this)."""
    return ListNodeTypesResponse(
        node_types=[
            NodeType(
                node_type_id="Standard_DS3_v2",
                memory_mb=14336,
                num_cores=4.0,
                description="Standard_DS3_v2",
                category="General Purpose",
            ),
            NodeType(
                node_type_id="Standard_DS4_v2",
                memory_mb=28672,
                num_cores=8.0,
                description="Standard_DS4_v2",
                category="General Purpose",
            ),
        ]
    )


@router.get("/list-zones", response_model=ListZonesResponse)
async def list_zones() -> ListZonesResponse:
    """Static zone list (local dev has no real availability zones)."""
    return ListZonesResponse(zones=["auto"], default_zone="auto")


@router.get("/spark-versions", response_model=GetSparkVersionsResponse)
async def spark_versions() -> GetSparkVersionsResponse:
    """Static Spark version catalog."""
    return GetSparkVersionsResponse(
        versions=[
            SparkVersion(key="13.3.x-scala2.12", name="13.3 LTS (Scala 2.12, Spark 3.4.1)"),
            SparkVersion(key="14.3.x-scala2.12", name="14.3 LTS (Scala 2.12, Spark 3.5.0)"),
        ]
    )


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    global _state
    _state.update(data)


async def reset() -> None:
    global _state
    _state = {"clusters": {}}
