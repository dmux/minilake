"""Unity Catalog function tests.

Driven through `w.functions.*`.

The registration half is ordinary CRUD. The half worth caring about is that a SQL
function is created as a real DuckDB macro, so a function registered through the UC
API is then *callable* from the Statement Execution API by its three-part name —
`test_sql_function_is_callable_by_three_part_name` is the test that would fail if
this ever quietly degraded to metadata-only.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.catalog import (
    ColumnTypeName,
    CreateFunction,
    CreateFunctionParameterStyle,
    CreateFunctionRoutineBody,
    CreateFunctionSecurityType,
    CreateFunctionSqlDataAccess,
    FunctionParameterInfo,
    FunctionParameterInfos,
)


def _sql_function(name: str, catalog_name: str, schema_name: str, definition: str) -> CreateFunction:
    """A one-argument DOUBLE -> DOUBLE SQL function."""
    return CreateFunction(
        name=name,
        catalog_name=catalog_name,
        schema_name=schema_name,
        input_params=FunctionParameterInfos(
            parameters=[
                FunctionParameterInfo(
                    name="amount",
                    type_text="DOUBLE",
                    type_name=ColumnTypeName.DOUBLE,
                    position=0,
                )
            ]
        ),
        data_type=ColumnTypeName.DOUBLE,
        full_data_type="DOUBLE",
        routine_body=CreateFunctionRoutineBody.SQL,
        routine_definition=definition,
        parameter_style=CreateFunctionParameterStyle.S,
        is_deterministic=True,
        sql_data_access=CreateFunctionSqlDataAccess.NO_SQL,
        is_null_call=False,
        security_type=CreateFunctionSecurityType.DEFINER,
        specific_name=name,
    )


@pytest.mark.crud
def test_create_and_get_function(workspace_client: WorkspaceClient, catalog_and_schema):
    cat, schema = catalog_and_schema
    created = workspace_client.functions.create(
        function_info=_sql_function("add_tax", cat.name, schema.name, "amount * 1.1")
    )

    assert created.full_name == f"{cat.name}.{schema.name}.add_tax"
    assert created.function_id
    assert created.routine_definition == "amount * 1.1"
    assert created.owner == "minilake-user"

    fetched = workspace_client.functions.get(name=created.full_name)
    assert fetched.name == "add_tax"
    assert fetched.input_params.parameters[0].name == "amount"


@pytest.mark.crud
def test_list_functions_scoped_to_schema(workspace_client: WorkspaceClient, catalog_and_schema):
    cat, schema = catalog_and_schema
    for name in ("f_one", "f_two"):
        workspace_client.functions.create(function_info=_sql_function(name, cat.name, schema.name, "amount"))

    names = {f.name for f in workspace_client.functions.list(catalog_name=cat.name, schema_name=schema.name)}
    assert names == {"f_one", "f_two"}


@pytest.mark.serial
@pytest.mark.workflow
def test_sql_function_is_callable_by_three_part_name(workspace_client: WorkspaceClient, catalog_and_schema):
    """The point of the whole feature: a UC function is real, not just registered."""
    cat, schema = catalog_and_schema
    warehouse = workspace_client.warehouses.create(name="fn_wh", cluster_size="Small").id

    workspace_client.functions.create(function_info=_sql_function("add_tax", cat.name, schema.name, "amount * 1.1"))

    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse,
        statement=f"SELECT {cat.name}.{schema.name}.add_tax(100) AS total",
    )
    assert float(result.result.data_array[0][0]) == pytest.approx(110.0)


@pytest.mark.serial
def test_deleting_a_function_drops_the_macro(workspace_client: WorkspaceClient, catalog_and_schema):
    """Delete must remove the DuckDB macro too, not just the metadata record."""
    cat, schema = catalog_and_schema
    warehouse = workspace_client.warehouses.create(name="fn_drop_wh", cluster_size="Small").id
    full_name = f"{cat.name}.{schema.name}.add_tax"

    workspace_client.functions.create(function_info=_sql_function("add_tax", cat.name, schema.name, "amount * 1.1"))
    workspace_client.functions.delete(name=full_name)

    with pytest.raises(DatabricksError):
        workspace_client.functions.get(name=full_name)

    with pytest.raises(DatabricksError):
        workspace_client.statement_execution.execute_statement(
            warehouse_id=warehouse, statement=f"SELECT {full_name}(1)"
        )


@pytest.mark.crud
def test_update_function_owner(workspace_client: WorkspaceClient, catalog_and_schema):
    cat, schema = catalog_and_schema
    created = workspace_client.functions.create(function_info=_sql_function("owned", cat.name, schema.name, "amount"))

    updated = workspace_client.functions.update(name=created.full_name, owner="someone-else")
    assert updated.owner == "someone-else"


@pytest.mark.error
def test_function_in_missing_schema_rejected(workspace_client: WorkspaceClient, catalog):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.functions.create(
            function_info=_sql_function("orphan", catalog.name, "no_such_schema", "amount")
        )
    assert "does not exist" in str(exc.value).lower()


@pytest.mark.error
def test_duplicate_function_rejected(workspace_client: WorkspaceClient, catalog_and_schema):
    cat, schema = catalog_and_schema
    workspace_client.functions.create(function_info=_sql_function("dupe", cat.name, schema.name, "amount"))
    with pytest.raises(DatabricksError) as exc:
        workspace_client.functions.create(function_info=_sql_function("dupe", cat.name, schema.name, "amount"))
    assert "already exists" in str(exc.value).lower()


@pytest.mark.error
def test_get_unknown_function_is_404(workspace_client: WorkspaceClient, catalog_and_schema):
    cat, schema = catalog_and_schema
    with pytest.raises(DatabricksError):
        workspace_client.functions.get(name=f"{cat.name}.{schema.name}.nope")
