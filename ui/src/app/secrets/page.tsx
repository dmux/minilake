"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
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
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import {
  createScope,
  deleteScope,
  deleteSecret,
  listScopes,
  listSecrets,
  putSecret,
} from "@/lib/api/secrets";
import { cn } from "@/lib/utils";

type PendingDelete = { kind: "scope"; scope: string } | { kind: "secret"; scope: string; key: string };

export default function SecretsPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [creatingScope, setCreatingScope] = useState(false);
  const [scopeName, setScopeName] = useState("");
  const [editingSecret, setEditingSecret] = useState<{ key: string } | null>(null);
  const [secretKey, setSecretKey] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);

  const scopes = useQuery({ queryKey: ["secret-scopes"], queryFn: listScopes });
  const secrets = useQuery({
    queryKey: ["secrets", selected],
    queryFn: () => listSecrets(selected as string),
    enabled: Boolean(selected),
  });

  const onError = (error: unknown) => toast.error(errorMessage(error));

  const addScope = useMutation({
    mutationFn: () => createScope(scopeName.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["secret-scopes"] });
      setSelected(scopeName.trim());
      setCreatingScope(false);
      setScopeName("");
      toast.success("Scope created");
    },
    onError,
  });

  const savePut = useMutation({
    mutationFn: () => putSecret(selected as string, secretKey.trim(), secretValue),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["secrets", selected] });
      setEditingSecret(null);
      setSecretKey("");
      setSecretValue("");
      toast.success("Secret saved");
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: (target: PendingDelete) =>
      target.kind === "scope" ? deleteScope(target.scope) : deleteSecret(target.scope, target.key),
    onSuccess: async (_data, target) => {
      await queryClient.invalidateQueries({ queryKey: ["secret-scopes"] });
      await queryClient.invalidateQueries({ queryKey: ["secrets", target.scope] });
      if (target.kind === "scope" && selected === target.scope) setSelected(null);
      setPendingDelete(null);
      toast.success("Deleted");
    },
    onError,
  });

  function openSecretDialog(key?: string) {
    setEditingSecret({ key: key ?? "" });
    setSecretKey(key ?? "");
    setSecretValue("");
  }

  return (
    <WorkspaceShell title="Secrets">
      {/* Stated up front, because a UI that lists keys invites the question. */}
      <p className="shrink-0 border-b bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        Values are never readable through the API — only keys and timestamps. Jobs resolve
        them at run time via <span className="font-mono">{"{{secrets/scope/key}}"}</span> in a
        task&apos;s <span className="font-mono">spark_env_vars</span>.
      </p>

      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="30%" minSize="20%" maxSize="45%" className="min-w-0">
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center justify-between gap-2 border-b px-2 py-1.5">
              <span className="text-xs font-medium text-muted-foreground">Scopes</span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  onClick={() => scopes.refetch()}
                  aria-label="Refresh scopes"
                >
                  <RefreshCw className="size-3.5" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7"
                  onClick={() => setCreatingScope(true)}
                >
                  <Plus className="size-3.5" />
                  New
                </Button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-auto py-1">
              {scopes.isLoading ? (
                <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" />
                  Loading…
                </div>
              ) : scopes.isError ? (
                <p className="px-3 py-2 text-xs text-destructive">{errorMessage(scopes.error)}</p>
              ) : (scopes.data ?? []).length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground">No scopes yet.</p>
              ) : (
                (scopes.data ?? []).map((scope) => (
                  <div
                    key={scope.name}
                    className={cn(
                      "flex items-center gap-1.5 px-2 py-1 hover:bg-accent",
                      selected === scope.name && "bg-accent",
                    )}
                  >
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                      onClick={() => setSelected(scope.name)}
                    >
                      <KeyRound className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate text-sm">{scope.name}</span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7 shrink-0"
                      onClick={() => setPendingDelete({ kind: "scope", scope: scope.name })}
                      aria-label={`Delete scope ${scope.name}`}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel defaultSize="70%" className="min-w-0">
          {!selected ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              <KeyRound className="size-8 opacity-40" />
              Select a scope to see its keys.
            </div>
          ) : (
            <div className="flex h-full min-h-0 flex-col">
              <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
                <span className="font-mono text-sm">{selected}</span>
                <Button variant="outline" size="sm" onClick={() => openSecretDialog()}>
                  <Plus className="size-3.5" />
                  New secret
                </Button>
              </div>

              <div className="min-h-0 flex-1 overflow-auto">
                <Table>
                  <TableHeader className="sticky top-0 bg-background">
                    <TableRow>
                      <TableHead>Key</TableHead>
                      <TableHead className="w-[200px]">Last updated</TableHead>
                      <TableHead className="w-[120px]" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(secrets.data ?? []).length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={3} className="py-10 text-center text-muted-foreground">
                          No secrets in this scope.
                        </TableCell>
                      </TableRow>
                    ) : (
                      (secrets.data ?? []).map((secret) => (
                        <TableRow key={secret.key}>
                          <TableCell className="font-mono text-xs">{secret.key}</TableCell>
                          <TableCell className="text-xs tabular-nums">
                            {secret.last_updated_timestamp
                              ? new Date(secret.last_updated_timestamp).toLocaleString()
                              : "—"}
                          </TableCell>
                          <TableCell>
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => openSecretDialog(secret.key)}
                              >
                                Replace
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() =>
                                  setPendingDelete({ kind: "secret", scope: selected, key: secret.key })
                                }
                                aria-label={`Delete secret ${secret.key}`}
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
              </div>
            </div>
          )}
        </ResizablePanel>
      </ResizablePanelGroup>

      <Dialog open={creatingScope} onOpenChange={setCreatingScope}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New scope</DialogTitle>
          </DialogHeader>
          <div className="grid gap-2 py-2">
            <Label htmlFor="scope-name">Scope name</Label>
            <Input
              id="scope-name"
              value={scopeName}
              onChange={(event) => setScopeName(event.target.value)}
              placeholder="my-scope"
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreatingScope(false)}>
              Cancel
            </Button>
            <Button onClick={() => addScope.mutate()} disabled={!scopeName.trim() || addScope.isPending}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(editingSecret)} onOpenChange={(open) => !open && setEditingSecret(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingSecret?.key ? "Replace secret" : "New secret"}</DialogTitle>
            <DialogDescription>
              The value is write-only — it cannot be read back here or through the API.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="secret-key">Key</Label>
              <Input
                id="secret-key"
                value={secretKey}
                onChange={(event) => setSecretKey(event.target.value)}
                disabled={Boolean(editingSecret?.key)}
                placeholder="api_token"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="secret-value">Value</Label>
              <Input
                id="secret-value"
                type="password"
                value={secretValue}
                onChange={(event) => setSecretValue(event.target.value)}
                autoFocus={Boolean(editingSecret?.key)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingSecret(null)}>
              Cancel
            </Button>
            <Button onClick={() => savePut.mutate()} disabled={!secretKey.trim() || savePut.isPending}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {pendingDelete?.kind === "scope" ? "scope" : "secret"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.kind === "scope"
                ? `“${pendingDelete.scope}” and every secret in it will be removed.`
                : `“${pendingDelete?.key}” will be removed from ${pendingDelete?.scope}.`}{" "}
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingDelete && remove.mutate(pendingDelete)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}
