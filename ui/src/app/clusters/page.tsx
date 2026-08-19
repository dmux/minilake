"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Plus, RefreshCw, RotateCw, Square, Trash2 } from "lucide-react";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import {
  createCluster,
  listClusters,
  listSparkVersions,
  permanentDeleteCluster,
  restartCluster,
  startCluster,
  terminateCluster,
} from "@/lib/api/clusters";
import type { Cluster } from "@/lib/api/types";

/** States the server moves out of on its own, so the table keeps polling. */
const TRANSIENT = new Set(["PENDING", "TERMINATING", "RESTARTING", "RESIZING"]);

function stateVariant(state: string) {
  if (state === "RUNNING") return "secondary" as const;
  if (state === "ERROR") return "destructive" as const;
  return "outline" as const;
}

export default function ClustersPage() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [sparkVersion, setSparkVersion] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Cluster | null>(null);

  const clusters = useQuery({
    queryKey: ["clusters"],
    queryFn: listClusters,
    // Transitions run on real asyncio delays (MINILAKE_CLUSTER_START_DELAY), so a
    // cluster reaches RUNNING seconds after the call returns. Poll only while
    // something is actually in flight.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((cluster) => TRANSIENT.has(cluster.state)) ? 2000 : false,
  });

  const versions = useQuery({ queryKey: ["spark-versions"], queryFn: listSparkVersions });

  const onError = (error: unknown) => toast.error(errorMessage(error));

  async function refresh(message: string) {
    await queryClient.invalidateQueries({ queryKey: ["clusters"] });
    toast.success(message);
  }

  const create = useMutation({
    mutationFn: () =>
      createCluster({
        cluster_name: name.trim(),
        spark_version: sparkVersion || versions.data?.[0]?.key || "14.3.x-scala2.12",
      }),
    onSuccess: async () => {
      setCreating(false);
      setName("");
      await refresh("Cluster created");
    },
    onError,
  });

  const start = useMutation({ mutationFn: startCluster, onSuccess: () => refresh("Starting"), onError });
  const restart = useMutation({ mutationFn: restartCluster, onSuccess: () => refresh("Restarting"), onError });
  const terminate = useMutation({
    mutationFn: terminateCluster,
    onSuccess: () => refresh("Terminating"),
    onError,
  });
  const remove = useMutation({
    mutationFn: permanentDeleteCluster,
    onSuccess: async () => {
      setPendingDelete(null);
      await refresh("Cluster removed");
    },
    onError,
  });

  return (
    <WorkspaceShell title="Clusters">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <Button variant="ghost" size="sm" onClick={() => clusters.refetch()}>
          <RefreshCw className="size-3.5" />
          Refresh
        </Button>
        <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
          <Plus className="size-3.5" />
          New cluster
        </Button>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {clusters.data?.length ?? 0} clusters
        </span>
      </div>

      {/* Said plainly, because the state machine is convincing enough to mislead. */}
      <p className="shrink-0 border-b bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        Clusters are a state machine only — they run no Spark. Jobs execute in their own
        containers, and SQL runs on warehouses.
      </p>

      <div className="min-h-0 flex-1 overflow-auto">
        {clusters.isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading…
          </div>
        ) : clusters.isError ? (
          <div className="p-4 text-sm text-destructive">{errorMessage(clusters.error)}</div>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 bg-background">
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-[200px]">Cluster ID</TableHead>
                <TableHead className="w-[130px]">State</TableHead>
                <TableHead className="w-[190px]">Spark version</TableHead>
                <TableHead className="w-[150px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(clusters.data ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                    No clusters yet.
                  </TableCell>
                </TableRow>
              ) : (
                (clusters.data ?? []).map((cluster) => {
                  const terminated = cluster.state === "TERMINATED";
                  return (
                    <TableRow key={cluster.cluster_id}>
                      <TableCell>{cluster.cluster_name ?? "—"}</TableCell>
                      <TableCell className="font-mono text-xs">{cluster.cluster_id}</TableCell>
                      <TableCell>
                        <Badge variant={stateVariant(cluster.state)}>{cluster.state}</Badge>
                      </TableCell>
                      <TableCell className="text-xs">{cluster.spark_version}</TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          {terminated ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => start.mutate(cluster.cluster_id)}
                              aria-label="Start cluster"
                            >
                              <Play className="size-3.5" />
                            </Button>
                          ) : (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => restart.mutate(cluster.cluster_id)}
                                aria-label="Restart cluster"
                              >
                                <RotateCw className="size-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => terminate.mutate(cluster.cluster_id)}
                                aria-label="Terminate cluster"
                              >
                                <Square className="size-3.5" />
                              </Button>
                            </>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setPendingDelete(cluster)}
                            aria-label="Remove cluster"
                          >
                            <Trash2 className="size-3.5 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New cluster</DialogTitle>
            <DialogDescription>Node type and worker count are not modelled.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="cluster-name">Name</Label>
              <Input
                id="cluster-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="dev-cluster"
                autoFocus
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="spark-version">Spark version</Label>
              <Select
                value={sparkVersion || versions.data?.[0]?.key || ""}
                onValueChange={(value) => setSparkVersion(String(value))}
                items={(versions.data ?? []).map((version) => ({ value: version.key, label: version.name }))}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(versions.data ?? []).map((version) => (
                    <SelectItem key={version.key} value={version.key}>
                      {version.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove cluster?</AlertDialogTitle>
            <AlertDialogDescription>
              “{pendingDelete?.cluster_name ?? pendingDelete?.cluster_id}” will be permanently
              deleted, not just terminated. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingDelete && remove.mutate(pendingDelete.cluster_id)}>
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}
