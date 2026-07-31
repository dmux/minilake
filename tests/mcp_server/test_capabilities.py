"""The MCP server advertises the capabilities we expect, over real Streamable HTTP."""

import pytest

pytestmark = pytest.mark.anyio


async def test_server_initializes_and_lists_tools(mcp_session):
    """A real MCP client can handshake and enumerate tools."""
    result = await mcp_session.list_tools()
    names = {tool.name for tool in result.tools}

    # One representative per tool module, so a module failing to register is caught.
    expected = {
        "run_sql",
        "list_warehouses",
        "list_catalogs",
        "list_jobs",
        "list_workspace",
        "upload_file",
        "dbfs_list",
        "list_secret_scopes",
        "list_clusters",
        "reset_state",
        "describe_catalog_tree",
        "run_python_script",
    }
    assert expected <= names, f"missing tools: {expected - names}"


async def test_tool_names_are_unique(mcp_session):
    """Duplicate registrations are dropped silently by the SDK, so assert on the count.

    With ~70 tools across 11 modules, a copy-paste collision would otherwise only show up
    as a log warning and a mysteriously absent tool.
    """
    result = await mcp_session.list_tools()
    names = [tool.name for tool in result.tools]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate tool names: {duplicates}"


async def test_every_tool_has_a_description(mcp_session):
    """Descriptions are how the model learns minilake's quirks; none may be blank."""
    result = await mcp_session.list_tools()
    undocumented = [t.name for t in result.tools if not (t.description or "").strip()]
    assert not undocumented, f"tools without a description: {undocumented}"


async def test_lists_resources_and_templates(mcp_session):
    """The guidance resources and the parameterised templates are both advertised."""
    static = await mcp_session.list_resources()
    static_uris = {str(r.uri) for r in static.resources}
    assert "minilake://capabilities" in static_uris
    assert "minilake://sql-dialect" in static_uris
    assert "minilake://pyspark-guide" in static_uris

    templates = await mcp_session.list_resource_templates()
    template_uris = {t.uriTemplate for t in templates.resourceTemplates}
    assert "minilake://table/{full_name}" in template_uris


async def test_lists_prompts(mcp_session):
    """All four prompts are advertised."""
    result = await mcp_session.list_prompts()
    names = {p.name for p in result.prompts}
    assert {"explore_data", "run_spark_job", "diagnose_error", "seed_test_fixture"} <= names


async def test_reads_capabilities_resource(mcp_session):
    """The capabilities resource states what is real and what returns NOT_IMPLEMENTED."""
    result = await mcp_session.read_resource("minilake://capabilities")
    text = result.contents[0].text
    assert "NOT_IMPLEMENTED" in text
    assert "DuckDB" in text


async def test_reads_pyspark_guide_resource(mcp_session):
    """The PySpark guide has to carry both ways of addressing a table.

    By path is the default and needs nothing; `spark.table()` needs the Unity Catalog
    connector wired up. A guide that mentions only one of them sends the agent down a
    dead end — which is what it did while it claimed three-part names could not work.
    """
    result = await mcp_session.read_resource("minilake://pyspark-guide")
    text = result.contents[0].text

    assert "delta" in text.lower()
    assert "/data/delta/" in text, "the by-path recipe"
    assert "unitycatalog-spark" in text, "the by-name recipe"
    assert "spark.table(" in text


async def test_prompt_renders_with_arguments(mcp_session):
    """A prompt returns usable message text with the argument interpolated."""
    result = await mcp_session.get_prompt("explore_data", {"question": "how many orders?"})
    rendered = " ".join(m.content.text for m in result.messages if hasattr(m.content, "text"))
    assert "how many orders?" in rendered
    assert "sql-dialect" in rendered
