"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Loader2, NotebookPen, RefreshCw } from "lucide-react";

import { WorkspaceShell } from "@/components/layout/workspace-shell";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/client";
import { getNotebookStatus } from "@/lib/api/notebook";

export default function NotebooksPage() {
  const status = useQuery({
    queryKey: ["notebook-status"],
    queryFn: getNotebookStatus,
    // JupyterLab is started in the background at boot and takes a few seconds to
    // bind its port. Poll until it is up, then stop.
    refetchInterval: (query) => (query.state.data?.running ? false : 2000),
  });

  const ready = status.data?.running;

  return (
    <WorkspaceShell title="Notebooks">
      {ready ? (
        // Same-origin by way of minilake's /jupyter proxy. That is what makes this
        // frame legal at all: jupyter-server sends `frame-ancestors 'self'`, so an
        // iframe pointing at its own port from this page would be blocked.
        <iframe
          src={status.data?.path ?? "/jupyter/lab"}
          title="JupyterLab"
          className="min-h-0 flex-1 border-0"
          // Needs same-origin (cookies, storage) and downloads for "Save as".
          sandbox="allow-scripts allow-same-origin allow-forms allow-downloads allow-popups allow-modals"
        />
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <div className="max-w-md space-y-4 text-center">
            <NotebookPen className="mx-auto size-10 text-muted-foreground opacity-40" />
            <NotebookMessage status={status.data} isLoading={status.isLoading} error={status.error} />
            <Button variant="outline" size="sm" onClick={() => status.refetch()}>
              <RefreshCw className="size-3.5" />
              Check again
            </Button>
          </div>
        </div>
      )}

      {ready ? (
        <div className="flex shrink-0 items-center gap-2 border-t px-3 py-1.5 text-xs text-muted-foreground">
          <span>
            Spark runs in sibling job containers, not in the kernel — see the quickstart
            notebook.
          </span>
          <a
            href={status.data?.path ?? "/jupyter/lab"}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 hover:text-foreground"
          >
            Open in a new tab
            <ExternalLink className="size-3" />
          </a>
        </div>
      ) : null}
    </WorkspaceShell>
  );
}

function NotebookMessage({
  status,
  isLoading,
  error,
}: {
  status?: { enabled: boolean; installed: boolean; running: boolean };
  isLoading: boolean;
  error: unknown;
}) {
  if (isLoading) {
    return (
      <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Checking the notebook server…
      </p>
    );
  }

  // A 404 here means the proxy was never mounted, i.e. the server was started with
  // the notebook disabled.
  if (error || !status?.enabled) {
    return (
      <div className="space-y-2 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Notebooks are turned off.</p>
        <p>
          Start minilake without <code className="font-mono text-xs">MINILAKE_NOTEBOOK=0</code> to
          enable the embedded JupyterLab.
        </p>
        {error ? <p className="text-xs">{errorMessage(error)}</p> : null}
      </div>
    );
  }

  if (!status.installed) {
    return (
      <div className="space-y-2 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">JupyterLab is not installed.</p>
        <p>
          This install lacks the notebook extra. Add it with{" "}
          <code className="font-mono text-xs">pip install &quot;minilake[notebook]&quot;</code>, or
          use the Docker image, which bundles it.
        </p>
      </div>
    );
  }

  return (
    <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      Starting JupyterLab…
    </p>
  );
}
