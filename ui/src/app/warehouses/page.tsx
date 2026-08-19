"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Plus, Square, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { WorkspaceShell } from "@/components/layout/workspace-shell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import {
  createWarehouse,
  deleteWarehouse,
  listWarehouses,
  startWarehouse,
  stopWarehouse,
} from "@/lib/api/warehouses";
import type { Warehouse } from "@/lib/api/types";

const CLUSTER_SIZES = ["2X-Small", "X-Small", "Small", "Medium", "Large", "X-Large"];

export default function WarehousesPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Warehouse | null>(null);
  const [name, setName] = useState("");
  const [clusterSize, setClusterSize] = useState("Small");

  const { data: warehouses = [], isLoading, isError, error } = useQuery({
    queryKey: ["warehouses"],
    queryFn: listWarehouses,
  });

  async function refresh(message: string) {
    await queryClient.invalidateQueries({ queryKey: ["warehouses"] });
    toast.success(message);
  }

  const onError = (mutationError: unknown) => toast.error(errorMessage(mutationError));

  const create = useMutation({
    mutationFn: () => createWarehouse(name.trim() || "warehouse", clusterSize),
    onSuccess: async () => {
      setOpen(false);
      setName("");
      await refresh("Warehouse created");
    },
    onError,
  });

  const start = useMutation({
    mutationFn: startWarehouse,
    onSuccess: () => refresh("Warehouse started"),
    onError,
  });

  const stop = useMutation({
    mutationFn: stopWarehouse,
    onSuccess: () => refresh("Warehouse stopped"),
    onError,
  });

  const remove = useMutation({
    mutationFn: deleteWarehouse,
    onSuccess: async () => {
      setPendingDelete(null);
      await refresh("Warehouse deleted");
    },
    onError,
  });

  return (
    <WorkspaceShell title="SQL warehouses">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger
            render={
              <Button size="sm">
                <Plus className="size-3.5" />
                Create warehouse
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create warehouse</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="warehouse-name">Name</Label>
                <Input
                  id="warehouse-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="analytics"
                />
              </div>
              <div className="space-y-2">
                <Label>Cluster size</Label>
                <Select
                  value={clusterSize}
                  onValueChange={(value) => setClusterSize(String(value))}
                  items={CLUSTER_SIZES.map((size) => ({ value: size, label: size }))}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CLUSTER_SIZES.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Recorded as metadata — minilake runs every warehouse on the same DuckDB engine.
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => create.mutate()} disabled={create.isPending}>
                {create.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
                Create
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {warehouses.length} warehouse{warehouses.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading…
          </div>
        ) : isError ? (
          <div className="p-4 text-sm text-destructive">{errorMessage(error)}</div>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 bg-background">
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-[140px]">ID</TableHead>
                <TableHead className="w-[120px]">State</TableHead>
                <TableHead className="w-[120px]">Size</TableHead>
                <TableHead className="w-[170px]">Created</TableHead>
                <TableHead className="w-[150px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {warehouses.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                    No warehouses yet. Create one to run queries.
                  </TableCell>
                </TableRow>
              ) : (
                warehouses.map((warehouse) => (
                  <TableRow key={warehouse.id}>
                    <TableCell className="font-medium">{warehouse.name}</TableCell>
                    <TableCell className="font-mono text-xs">{warehouse.id}</TableCell>
                    <TableCell>
                      <Badge variant={warehouse.state === "RUNNING" ? "secondary" : "outline"}>
                        {warehouse.state}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">{warehouse.cluster_size}</TableCell>
                    <TableCell className="text-xs tabular-nums">
                      {warehouse.created_at ? new Date(warehouse.created_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {warehouse.state === "RUNNING" ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => stop.mutate(warehouse.id)}
                            aria-label="Stop"
                          >
                            <Square className="size-3.5" />
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => start.mutate(warehouse.id)}
                            aria-label="Start"
                          >
                            <Play className="size-3.5" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPendingDelete(warehouse)}
                          aria-label="Delete"
                        >
                          <Trash2 className="size-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>
      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete warehouse?</AlertDialogTitle>
            <AlertDialogDescription>
              “{pendingDelete?.name}” will be removed, along with the data held in its DuckDB
              connection. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingDelete && remove.mutate(pendingDelete.id)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}
