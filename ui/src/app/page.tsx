"use client"

import React, { useState, useEffect, useRef } from "react"
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Play, Loader2, Database, Table as TableIcon, Moon, Sun, Monitor } from "lucide-react"
import { useTheme } from "next-themes"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import Editor, { useMonaco } from '@monaco-editor/react'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { executeSql, getWarehouses } from "@/lib/api"

export default function Workspace() {
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const monaco = useMonaco()
  
  const [query, setQuery] = useState("SELECT 1 AS test_col;")
  const [warehouseId, setWarehouseId] = useState("default")
  const [warehouses, setWarehouses] = useState<string[]>([])
  
  const [isRunning, setIsRunning] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<any[]>([])

  const [catalogs, setCatalogs] = useState<any[]>([])
  
  useEffect(() => {
    setMounted(true)
    // Fetch warehouses
    getWarehouses().then(wh => {
      setWarehouses(wh)
      if (wh.length > 0) setWarehouseId(wh[0])
    }).catch(console.error)
  }, [])

  useEffect(() => {
    // Load history from local storage
    try {
      const stored = localStorage.getItem("minilake_history")
      if (stored) setHistory(JSON.parse(stored))
    } catch(e) {}
  }, [])

  const saveHistory = (item: any) => {
    const newHistory = [item, ...history].slice(0, 50)
    setHistory(newHistory)
    try {
      localStorage.setItem("minilake_history", JSON.stringify(newHistory))
    } catch(e) {}
  }

  const runQuery = async () => {
    if (!query.trim()) return
    
    setIsRunning(true)
    setError(null)
    setResult(null)
    
    const startTime = Date.now()
    try {
      const res = await executeSql(query, warehouseId)
      setResult(res)
      saveHistory({
        query,
        time: new Date().toISOString(),
        duration: Date.now() - startTime,
        status: "success",
        rows: res.result?.row_count || 0
      })
    } catch (err: any) {
      setError(err.message)
      saveHistory({
        query,
        time: new Date().toISOString(),
        duration: Date.now() - startTime,
        status: "error",
        error: err.message
      })
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* Top Navbar */}
      <header className="flex h-14 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <h1 className="font-semibold">Minilake Workspace</h1>
        </div>
        <div className="flex items-center gap-4">
          <select 
            value={warehouseId} 
            onChange={e => setWarehouseId(e.target.value)}
            className="text-sm bg-transparent border rounded p-1"
          >
            {warehouses.map(w => (
              <option key={w} value={w}>{w}</option>
            ))}
          </select>
          <DropdownMenu>
            {/* @ts-ignore */}
            <DropdownMenuTrigger className="inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring hover:bg-accent hover:text-accent-foreground h-9 w-9">
              <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
              <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
              <span className="sr-only">Toggle theme</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setTheme("light")}>
                Light
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme("dark")}>
                Dark
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme("system")}>
                System
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* @ts-ignore */}
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Left Sidebar - Explorer */}
        <ResizablePanel defaultSize={20} minSize={15} maxSize={30} className="bg-muted/30">
          <div className="p-4 h-full flex flex-col">
            <h2 className="text-sm font-semibold mb-4">Database Explorer</h2>
            <ScrollArea className="flex-1">
              <div className="text-sm text-muted-foreground">
                <p>Explorer coming soon.</p>
                <p className="mt-2 text-xs">Run SHOW CATALOGS to list catalogs.</p>
              </div>
            </ScrollArea>
          </div>
        </ResizablePanel>
        
        <ResizableHandle withHandle />
        
        {/* Right Main Area */}
        <ResizablePanel defaultSize={80} className="flex flex-col">
          {/* @ts-ignore */}
          <ResizablePanelGroup direction="vertical">
            {/* Top - Editor */}
            <ResizablePanel defaultSize={50} minSize={20} className="flex flex-col border-b">
              <div className="flex items-center justify-between p-2 border-b bg-muted/20">
                <div className="flex items-center gap-2">
                  <Button 
                    size="sm" 
                    onClick={runQuery} 
                    disabled={isRunning}
                    className="gap-2"
                  >
                    {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    Run
                  </Button>
                </div>
              </div>
              <div className="flex-1 relative">
                <Editor
                  height="100%"
                  language="sql"
                  theme={mounted && theme === "dark" ? "vs-dark" : "light"}
                  value={query}
                  onChange={(val) => setQuery(val || "")}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 14,
                    wordWrap: "on",
                    padding: { top: 10 }
                  }}
                />
              </div>
            </ResizablePanel>
            
            <ResizableHandle withHandle />
            
            {/* Bottom - Results */}
            <ResizablePanel defaultSize={50} minSize={20}>
              <Tabs defaultValue="results" className="h-full flex flex-col">
                <div className="border-b px-4">
                  <TabsList className="h-10 bg-transparent">
                    <TabsTrigger value="results" className="data-[state=active]:bg-muted data-[state=active]:shadow-none border-b-2 border-transparent data-[state=active]:border-primary rounded-none">
                      Results
                    </TabsTrigger>
                    <TabsTrigger value="history" className="data-[state=active]:bg-muted data-[state=active]:shadow-none border-b-2 border-transparent data-[state=active]:border-primary rounded-none">
                      History
                    </TabsTrigger>
                  </TabsList>
                </div>
                
                <TabsContent value="results" className="flex-1 m-0 overflow-hidden">
                  {isRunning ? (
                    <div className="flex h-full items-center justify-center">
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                  ) : error ? (
                    <div className="p-4 text-red-500 bg-red-500/10 h-full overflow-auto font-mono text-sm">
                      {error}
                    </div>
                  ) : result?.result?.columns ? (
                    <ScrollArea className="h-full">
                      <Table>
                        <TableHeader className="bg-muted/50 sticky top-0">
                          <TableRow>
                            {result.result.columns.map((col: any, i: number) => (
                              <TableHead key={i} className="font-semibold whitespace-nowrap">
                                {col.name}
                              </TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {result.result.data_array?.map((row: any[], i: number) => (
                            <TableRow key={i}>
                              {row.map((cell: any, j: number) => (
                                <TableCell key={j} className="whitespace-nowrap font-mono text-sm">
                                  {cell === null ? <span className="text-muted-foreground italic">null</span> : String(cell)}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                          {!result.result.data_array?.length && (
                            <TableRow>
                              <TableCell colSpan={result.result.columns.length} className="text-center py-8 text-muted-foreground">
                                No rows returned.
                              </TableCell>
                            </TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">
                      Run a query to see results.
                    </div>
                  )}
                </TabsContent>
                
                <TabsContent value="history" className="flex-1 m-0 overflow-hidden">
                   <ScrollArea className="h-full">
                    <Table>
                      <TableHeader className="bg-muted/50 sticky top-0">
                        <TableRow>
                          <TableHead>Time</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Duration (ms)</TableHead>
                          <TableHead>Query</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {history.map((item, i) => (
                          <TableRow key={i}>
                            <TableCell className="whitespace-nowrap">{new Date(item.time).toLocaleTimeString()}</TableCell>
                            <TableCell>
                              <span className={`px-2 py-1 rounded text-xs ${item.status === 'success' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'}`}>
                                {item.status}
                              </span>
                            </TableCell>
                            <TableCell>{item.duration}</TableCell>
                            <TableCell className="font-mono text-xs max-w-[300px] truncate">{item.query}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </ScrollArea>
                </TabsContent>
              </Tabs>
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}
