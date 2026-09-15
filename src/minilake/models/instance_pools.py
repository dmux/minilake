"""Instance pool models (Databricks Instance Pools API 2.0)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CreateInstancePoolRequest(BaseModel):
    instance_pool_name: Optional[str] = None
    node_type_id: Optional[str] = None
    min_idle_instances: Optional[int] = None
    max_capacity: Optional[int] = None
    idle_instance_autotermination_minutes: Optional[int] = None
    enable_elastic_disk: Optional[bool] = None
    custom_tags: Optional[Dict[str, str]] = None
    preloaded_spark_versions: Optional[List[str]] = None
    preloaded_docker_images: Optional[List[Dict[str, Any]]] = None
    disk_spec: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class EditInstancePoolRequest(CreateInstancePoolRequest):
    instance_pool_id: str


class DeleteInstancePoolRequest(BaseModel):
    instance_pool_id: str


class InstancePoolStats(BaseModel):
    """Instance counts. Always zero here: no instances are ever provisioned."""

    used_count: int = 0
    idle_count: int = 0
    pending_used_count: int = 0
    pending_idle_count: int = 0


class InstancePoolAndStats(BaseModel):
    instance_pool_id: str
    instance_pool_name: Optional[str] = None
    node_type_id: Optional[str] = None
    min_idle_instances: Optional[int] = None
    max_capacity: Optional[int] = None
    idle_instance_autotermination_minutes: Optional[int] = None
    enable_elastic_disk: Optional[bool] = None
    custom_tags: Optional[Dict[str, str]] = None
    default_tags: Optional[Dict[str, str]] = None
    preloaded_spark_versions: Optional[List[str]] = None
    preloaded_docker_images: Optional[List[Dict[str, Any]]] = None
    disk_spec: Optional[Dict[str, Any]] = None
    state: Optional[str] = None
    stats: Optional[InstancePoolStats] = None


class CreateInstancePoolResponse(BaseModel):
    instance_pool_id: str


class ListInstancePools(BaseModel):
    instance_pools: List[InstancePoolAndStats] = []
