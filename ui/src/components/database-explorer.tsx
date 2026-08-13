"use client"

import React, { useEffect, useState } from "react"
import { getCatalogs, getSchemas, getTables, CatalogInfo, SchemaInfo, TableInfo } from "@/lib/api"
import { ChevronRight, ChevronDown, Database, Folder, Table2, Loader2 } from "lucide-react"

export function DatabaseExplorer({
  onSelectTable,
}: {
  onSelectTable?: (catalog: string, schema: string, table: string) => void
}) {
  const [catalogs, setCatalogs] = useState<CatalogInfo[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getCatalogs().then(data => {
      setCatalogs(data)
      setLoading(false)
    })
  }, [])

  if (loading) {
    return (
      <div className="flex justify-center items-center h-20 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    )
  }

  if (catalogs.length === 0) {
    return <div className="p-4 text-xs text-muted-foreground">No catalogs found.</div>
  }

  return (
    <div className="flex flex-col text-sm h-full overflow-auto">
      {catalogs.map(catalog => (
        <CatalogNode key={catalog.name} catalog={catalog} onSelectTable={onSelectTable} />
      ))}
    </div>
  )
}

function CatalogNode({ catalog, onSelectTable }: { catalog: CatalogInfo, onSelectTable?: any }) {
  const [expanded, setExpanded] = useState(false)
  const [schemas, setSchemas] = useState<SchemaInfo[]>([])
  const [loading, setLoading] = useState(false)

  const toggle = () => {
    if (!expanded && schemas.length === 0) {
      setLoading(true)
      getSchemas(catalog.name).then(data => {
        setSchemas(data)
        setLoading(false)
      })
    }
    setExpanded(!expanded)
  }

  return (
    <div className="flex flex-col">
      <div
        className="flex items-center space-x-1 py-1 px-2 hover:bg-accent cursor-pointer group"
        onClick={toggle}
      >
        <span className="w-4 h-4 flex items-center justify-center text-muted-foreground">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
        <Database className="h-3.5 w-3.5 text-blue-500" />
        <span className="font-medium truncate">{catalog.name}</span>
      </div>
      {expanded && (
        <div className="flex flex-col pl-4 border-l border-border ml-4 mt-0.5 mb-1">
          {schemas.length === 0 && !loading && (
            <div className="text-xs text-muted-foreground italic px-2 py-1">No schemas</div>
          )}
          {schemas.map(schema => (
            <SchemaNode key={schema.name} schema={schema} onSelectTable={onSelectTable} />
          ))}
        </div>
      )}
    </div>
  )
}

function SchemaNode({ schema, onSelectTable }: { schema: SchemaInfo, onSelectTable?: any }) {
  const [expanded, setExpanded] = useState(false)
  const [tables, setTables] = useState<TableInfo[]>([])
  const [loading, setLoading] = useState(false)

  const toggle = () => {
    if (!expanded && tables.length === 0) {
      setLoading(true)
      getTables(schema.catalog_name, schema.name).then(data => {
        setTables(data)
        setLoading(false)
      })
    }
    setExpanded(!expanded)
  }

  return (
    <div className="flex flex-col">
      <div
        className="flex items-center space-x-1 py-1 px-2 hover:bg-accent cursor-pointer group"
        onClick={toggle}
      >
        <span className="w-4 h-4 flex items-center justify-center text-muted-foreground">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
        <Folder className="h-3.5 w-3.5 text-amber-500" />
        <span className="truncate">{schema.name}</span>
      </div>
      {expanded && (
        <div className="flex flex-col pl-4 border-l border-border ml-4 mt-0.5 mb-1">
           {tables.length === 0 && !loading && (
            <div className="text-xs text-muted-foreground italic px-2 py-1">No tables</div>
          )}
          {tables.map(table => (
            <div
              key={table.name}
              className="flex items-center space-x-1.5 py-1 px-2 hover:bg-accent cursor-pointer group truncate"
              onClick={() => onSelectTable?.(table.catalog_name, table.schema_name, table.name)}
            >
              <Table2 className="h-3 w-3 text-emerald-500 shrink-0" />
              <span className="text-xs truncate">{table.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
