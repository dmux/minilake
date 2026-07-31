"""Unity Catalog Pydantic models."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from minilake.errors import DatabricksError


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
    """Column metadata, matching the SDK's `catalog.ColumnInfo`.

    Every type field is optional because the SDK's is: callers legitimately send only
    `type_name`, only `type_text`, or both. `resolved_type_text()` picks whichever is
    present so the caller does not have to send a redundant pair.
    """

    name: str
    type_text: Optional[str] = None
    type_name: Optional[str] = None
    type_precision: Optional[int] = None
    type_scale: Optional[int] = None
    type_json: Optional[str] = None
    position: Optional[int] = None
    nullable: bool = True
    comment: Optional[str] = None

    class Config:
        extra = "allow"

    def resolved_type_text(self) -> str:
        """The type spelling to parse, preferring the explicit text over the enum name.

        DECIMAL is the one case where `type_name` alone is not enough — the precision and
        scale live in their own fields.
        """
        if self.type_text:
            return self.type_text
        if self.type_name:
            if self.type_name.upper() == "DECIMAL" and self.type_precision is not None:
                return f"DECIMAL({self.type_precision},{self.type_scale or 0})"
            return self.type_name
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Column '{self.name}' needs either type_text or type_name",
            status_code=400,
        )


class TableInfo(BaseModel):
    """Table metadata."""

    name: str
    catalog_name: str
    schema_name: str
    full_name: Optional[str] = None
    # Spark's Unity Catalog connector reads this from the table it just fetched and sends
    # it back to /temporary-table-credentials — without it, it cannot request access.
    table_id: Optional[str] = None
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


class UpdateTableRequest(BaseModel):
    """Request to update a table's metadata."""

    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    owner: Optional[str] = None


class UpdateVolumeRequest(BaseModel):
    """Request to update a volume's metadata."""

    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    owner: Optional[str] = None


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


class TemporaryCredentials(BaseModel):
    """Credentials vended for one table or path.

    Every field is null here, which is the same answer the reference Unity Catalog server
    gives for a `file://` location: there is nothing to vend, because the data sits on a
    filesystem the client already has. minilake's tables always live on the shared volume,
    so this is the only shape it ever needs to return.
    """

    aws_temp_credentials: Optional[Dict[str, str]] = None
    azure_user_delegation_sas: Optional[Dict[str, str]] = None
    gcp_oauth_token: Optional[Dict[str, str]] = None
    expiration_time: Optional[int] = None


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
