"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Warehouse } from "lucide-react";
import { useEffect } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { errorMessage } from "@/lib/api/client";
import { createWarehouse, listWarehouses } from "@/lib/api/warehouses";
import { useWorkspaceStore } from "@/stores/workspace";

/** The warehouse every statement runs on — Athena's workgroup selector. */
export function WarehousePicker() {
  const queryClient = useQueryClient();
  const warehouseId = useWorkspaceStore((s) => s.warehouseId);
  const setWarehouseId = useWorkspaceStore((s) => s.setWarehouseId);

  const { data: warehouses = [], isLoading } = useQuery({
    queryKey: ["warehouses"],
    queryFn: listWarehouses,
  });

  // A fresh minilake seeds no warehouses, and executing against an unknown id is
  // a 400 — so without this the Run button fails on every first visit. Select the
  // first available one, and drop a stale persisted id that no longer exists.
  useEffect(() => {
    if (isLoading || warehouses.length === 0) return;
    if (!warehouseId || !warehouses.some((w) => w.id === warehouseId)) {
      setWarehouseId(warehouses[0].id);
    }
  }, [isLoading, warehouses, warehouseId, setWarehouseId]);

  const create = useMutation({
    mutationFn: () => createWarehouse("minilake-ui"),
    onSuccess: async (warehouse) => {
      setWarehouseId(warehouse.id);
      await queryClient.invalidateQueries({ queryKey: ["warehouses"] });
      toast.success(`Created warehouse ${warehouse.name}`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (isLoading) {
    return (
      <div className="flex h-9 items-center gap-2 px-2 text-sm text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Warehouses
      </div>
    );
  }

  if (warehouses.length === 0) {
    return (
      <Button size="sm" variant="outline" onClick={() => create.mutate()} disabled={create.isPending}>
        {create.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
        Create warehouse
      </Button>
    );
  }

  return (
    // `items` is what makes <SelectValue> render the warehouse's name; without it
    // Base UI shows the raw value, which here is an opaque id.
    <Select
      value={warehouseId ?? undefined}
      onValueChange={setWarehouseId}
      items={warehouses.map((w) => ({ value: w.id, label: w.name }))}
    >
      <SelectTrigger size="sm" className="w-[200px]" aria-label="Warehouse">
        <Warehouse className="size-3.5 text-muted-foreground" />
        <SelectValue placeholder="Select warehouse" />
      </SelectTrigger>
      <SelectContent>
        {warehouses.map((warehouse) => (
          <SelectItem key={warehouse.id} value={warehouse.id}>
            {warehouse.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
