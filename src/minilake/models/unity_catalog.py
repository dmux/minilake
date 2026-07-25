"""Unity Catalog Pydantic models."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TableType(str, Enum):
    """Table type enumeration."""

    MANAGED = "MANAGED"
    EXTERNAL = "EXTERNAL"


class VolumeType(str, Enum):
    """Volume type enumeration."""

    MANAGED = "MANAGED"
    EXTERNAL = "EXTERNAL"


class CatalogInfo(BaseModel):
    """Catalog metadata."""

    name: str
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    owner: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    class Config:
        extra = "allow"


class SchemaInfo(BaseModel):
    """Schema metadata."""

    name: str
    catalog_name: str
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    owner: Optional[str] = None
    full_name: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    class Config:
        extra = "allow"


class ColumnInfo(BaseModel):
    """Column metadata."""

    name: str
    type_text: str
    nullable: bool = True
    comment: Optional[str] = None

    class Config:
        extra = "allow"


class TableInfo(BaseModel):
    """Table metadata."""

    name: str
    catalog_name: str
    schema_name: str
    full_name: Optional[str] = None
    table_type: str = "MANAGED"
    data_source_format: Optional[str] = None
    storage_location: Optional[str] = None
    comment: Optional[str] = None
    columns: Optional[List[ColumnInfo]] = None
    properties: Optional[Dict[str, str]] = None
    owner: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    class Config:
        extra = "allow"


class VolumeInfo(BaseModel):
    """Volume metadata (external file storage)."""

    name: str
    catalog_name: str
    schema_name: str
    full_name: Optional[str] = None
    volume_type: str = "MANAGED"
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    owner: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    class Config:
        extra = "allow"


class CreateCatalogRequest(BaseModel):
    """Request to create a catalog."""

    name: str
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None


class CreateSchemaRequest(BaseModel):
    """Request to create a schema."""

    name: str
    catalog_name: str
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None


class UpdateSchemaRequest(BaseModel):
    """Request to update a schema."""

    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None


class UpdateCatalogRequest(BaseModel):
    """Request to update a catalog."""

    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None


class CreateTableRequest(BaseModel):
    """Request to create a table."""

    name: str
    catalog_name: str
    schema_name: str
    table_type: str = "MANAGED"
    data_source_format: Optional[str] = None
    storage_location: Optional[str] = None
    columns: Optional[List[ColumnInfo]] = None
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None


class CreateVolumeRequest(BaseModel):
    """Request to create a volume."""

    name: str
    catalog_name: str
    schema_name: str
    volume_type: str = "MANAGED"
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None


class ListCatalogsResponse(BaseModel):
    """Response to list catalogs."""

    catalogs: List[CatalogInfo] = Field(default_factory=list)


class ListSchemasResponse(BaseModel):
    """Response to list schemas."""

    schemas: List[SchemaInfo] = Field(default_factory=list)


class ListTablesResponse(BaseModel):
    """Response to list tables."""

    tables: List[TableInfo] = Field(default_factory=list)


class ListVolumesResponse(BaseModel):
    """Response to list volumes."""

    volumes: List[VolumeInfo] = Field(default_factory=list)
