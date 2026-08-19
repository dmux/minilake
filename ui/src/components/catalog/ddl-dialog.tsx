"use client";

import { Copy } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Table } from "@/lib/api/types";
import { generateCreateTable } from "@/lib/ddl";

/** Athena's "Generate table DDL", rendered from Unity Catalog's column metadata. */
export function DdlDialog({
  table,
  onOpenChange,
}: {
  table: Table | null;
  onOpenChange: (open: boolean) => void;
}) {
  const ddl = useMemo(() => (table ? generateCreateTable(table) : ""), [table]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(ddl);
      toast.success("DDL copied to clipboard");
    } catch {
      toast.error("Clipboard is not available");
    }
  }

  return (
    <Dialog open={Boolean(table)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Table DDL</DialogTitle>
          <DialogDescription>
            {table ? `${table.catalog_name}.${table.schema_name}.${table.name}` : ""}
          </DialogDescription>
        </DialogHeader>

        <pre className="max-h-[60vh] overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">{ddl}</pre>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={copy}>
            <Copy className="size-3.5" />
            Copy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
