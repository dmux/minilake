"""Clusters API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class CreateClusterRequest(BaseModel):
    """Accepts (and ignores) the many optional real-Databricks fields we don't
    model (aws_attributes, docker_image, policy_id, ...) so real SDK/Terraform
    payloads don't get rejected just for including them."""

    model_config = ConfigDict(extra="ignore")

    spark_version: str
    cluster_name: Optional[str] = None
    node_type_id: Optional[str] = None
    driver_node_type_id: Optional[str] = None
    num_workers: Optional[int] = None
    autotermination_minutes: Optional[int] = None
    spark_conf: Optional[Dict[str, str]] = None
    spark_env_vars: Optional[Dict[str, str]] = None
    custom_tags: Optional[Dict[str, str]] = None
    autoscale: Optional[Dict[str, Any]] = None


class EditClusterRequest(CreateClusterRequest):
    cluster_id: str


class CreateClusterResponse(BaseModel):
    cluster_id: str


class ClusterInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cluster_id: str
    cluster_name: Optional[str] = None
    spark_version: str
    node_type_id: Optional[str] = None
    driver_node_type_id: Optional[str] = None
    num_workers: Optional[int] = None
    autotermination_minutes: Optional[int] = None
    spark_conf: Optional[Dict[str, str]] = None
    spark_env_vars: Optional[Dict[str, str]] = None
    custom_tags: Optional[Dict[str, str]] = None
    autoscale: Optional[Dict[str, Any]] = None
    state: str
    state_message: str = ""
    creator_user_name: str = "minilake-user"
    start_time: Optional[int] = None
    terminated_time: Optional[int] = None
    last_restarted_time: Optional[int] = None
    default_tags: Optional[Dict[str, str]] = None


class ListClustersResponse(BaseModel):
    clusters: List[ClusterInfo] = []


class ClusterIdRequest(BaseModel):
    cluster_id: str


class RestartClusterRequest(BaseModel):
    cluster_id: str
    restart_user: Optional[str] = None


class ResizeClusterRequest(BaseModel):
    cluster_id: str
    num_workers: Optional[int] = None
    autoscale: Optional[Dict[str, Any]] = None


class ChangeClusterOwnerRequest(BaseModel):
    cluster_id: str
    owner_username: str


class ClusterEventsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cluster_id: str
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    order: Optional[str] = None
    event_types: Optional[List[str]] = None
    offset: Optional[int] = None
    limit: Optional[int] = None
    page_size: Optional[int] = None
    page_token: Optional[str] = None


class ClusterEventsResponse(BaseModel):
    events: List[Dict[str, Any]] = []


class NodeType(BaseModel):
    node_type_id: str
    memory_mb: int
    num_cores: float
    description: str
    category: Optional[str] = None


class ListNodeTypesResponse(BaseModel):
    node_types: List[NodeType]


class ListZonesResponse(BaseModel):
    zones: List[str]
    default_zone: str


class SparkVersion(BaseModel):
    key: str
    name: str


class GetSparkVersionsResponse(BaseModel):
    versions: List[SparkVersion]
