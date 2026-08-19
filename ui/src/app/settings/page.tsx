"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useTheme } from "next-themes";
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
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useIsMounted } from "@/hooks/use-is-mounted";
import { getCurrentUser, getHealth, getServices, resetState } from "@/lib/api/admin";
import { errorMessage } from "@/lib/api/client";
import { useWorkspaceStore } from "@/stores/workspace";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { theme, setTheme } = useTheme();
  // The stored theme is only known in the browser; rendering it during the
  // prerender would be a hydration mismatch.
  const mounted = useIsMounted();

  const autoLimit = useWorkspaceStore((s) => s.autoLimit);
  const setAutoLimit = useWorkspaceStore((s) => s.setAutoLimit);
  const autoLimitRows = useWorkspaceStore((s) => s.autoLimitRows);
  const setAutoLimitRows = useWorkspaceStore((s) => s.setAutoLimitRows);
  const fontSize = useWorkspaceStore((s) => s.editorFontSize);
  const setFontSize = useWorkspaceStore((s) => s.setEditorFontSize);
  const autocomplete = useWorkspaceStore((s) => s.autocomplete);
  const setAutocomplete = useWorkspaceStore((s) => s.setAutocomplete);

  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 15_000 });
  const services = useQuery({ queryKey: ["services"], queryFn: getServices });
  const currentUser = useQuery({ queryKey: ["current-user"], queryFn: getCurrentUser });

  const reset = useMutation({
    mutationFn: (full: boolean) => resetState(full),
    onSuccess: async () => {
      // Everything on screen was derived from state that no longer exists.
      await queryClient.invalidateQueries();
      toast.success("Workspace state reset");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <WorkspaceShell title="Settings">
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className="mx-auto grid max-w-4xl gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Appearance</CardTitle>
              <CardDescription>Light, dark, or follow the operating system.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between gap-4">
                <Label htmlFor="theme">Theme</Label>
                <Select
                  value={mounted ? (theme ?? "system") : "system"}
                  onValueChange={(value) => setTheme(String(value))}
                  items={{ light: "Light", dark: "Dark", system: "System" }}
                >
                  <SelectTrigger id="theme" className="w-[180px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="light">Light</SelectItem>
                    <SelectItem value="dark">Dark</SelectItem>
                    <SelectItem value="system">System</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Editor</CardTitle>
              <CardDescription>Applies to every query tab.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label htmlFor="autocomplete">Autocomplete</Label>
                  <p className="text-xs text-muted-foreground">
                    Suggest catalogs, schemas, tables and columns from Unity Catalog.
                  </p>
                </div>
                <Switch id="autocomplete" checked={autocomplete} onCheckedChange={setAutocomplete} />
              </div>

              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label htmlFor="auto-limit-setting">Auto limit</Label>
                  <p className="text-xs text-muted-foreground">
                    Wrap bare SELECTs in a row cap. Statements with their own LIMIT are left alone.
                  </p>
                </div>
                <Switch id="auto-limit-setting" checked={autoLimit} onCheckedChange={setAutoLimit} />
              </div>

              <div className="flex items-center justify-between gap-4">
                <Label htmlFor="auto-limit-rows">Auto limit rows</Label>
                <Input
                  id="auto-limit-rows"
                  type="number"
                  min={1}
                  className="w-[180px]"
                  value={autoLimitRows}
                  onChange={(event) => setAutoLimitRows(Math.max(1, Number(event.target.value) || 1))}
                />
              </div>

              <div className="flex items-center justify-between gap-4">
                <Label htmlFor="font-size">Font size</Label>
                <Input
                  id="font-size"
                  type="number"
                  min={10}
                  max={24}
                  className="w-[180px]"
                  value={fontSize}
                  onChange={(event) => setFontSize(Math.min(24, Math.max(10, Number(event.target.value) || 13)))}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Server</CardTitle>
              <CardDescription>Status of the minilake instance serving this page.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                {health.isLoading ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : health.isError ? (
                  <XCircle className="size-4 text-destructive" />
                ) : (
                  <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-500" />
                )}
                <span>
                  {health.isLoading
                    ? "Checking…"
                    : health.isError
                      ? errorMessage(health.error)
                      : `Healthy (${health.data?.status})`}
                </span>
              </div>

              <div className="space-y-2">
                <Label>Signed in as</Label>
                <p className="text-sm">
                  {currentUser.isLoading
                    ? "…"
                    : currentUser.isError
                      ? "—"
                      : (currentUser.data?.displayName ?? currentUser.data?.userName ?? "—")}
                  {currentUser.data?.emails?.[0]?.value ? (
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {currentUser.data.emails[0].value}
                    </span>
                  ) : null}
                </p>
                {/* Not a login: minilake accepts any token and reports one user. */}
                <p className="text-xs text-muted-foreground">
                  minilake has no authentication — every request is this user.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Enabled services</Label>
                <div className="flex flex-wrap gap-1.5">
                  {Object.keys(services.data?.services ?? {}).map((name) => (
                    <Badge key={name} variant="outline">
                      {name}
                    </Badge>
                  ))}
                  {Object.keys(services.data?.services ?? {}).length === 0 ? (
                    <span className="text-xs text-muted-foreground">—</span>
                  ) : null}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-destructive/40">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <AlertTriangle className="size-4 text-destructive" />
                Reset workspace
              </CardTitle>
              <CardDescription>
                Clears every service&apos;s state — catalogs, tables, warehouses, saved queries and query history.
                A full reset also wipes the warehouse data itself.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex gap-2">
              <AlertDialog>
                <AlertDialogTrigger
                  render={
                    <Button variant="outline" size="sm">
                      Reset state
                    </Button>
                  }
                />
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Reset all service state?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Catalogs, schemas, tables, warehouses, saved queries and query history will be cleared. This
                      cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => reset.mutate(false)}>Reset</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>

              <AlertDialog>
                <AlertDialogTrigger
                  render={
                    <Button variant="destructive" size="sm">
                      Full reset
                    </Button>
                  }
                />
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Wipe all data?</AlertDialogTitle>
                    <AlertDialogDescription>
                      In addition to the state above, this deletes the DuckDB data behind every warehouse and the
                      Unity Catalog database. This cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => reset.mutate(true)}>Wipe everything</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </CardContent>
          </Card>
        </div>
      </div>
    </WorkspaceShell>
  );
}
