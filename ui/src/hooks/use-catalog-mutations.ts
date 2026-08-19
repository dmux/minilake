"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  createCatalog,
  createSchema,
  createTable,
  createVolume,
  deleteCatalog,
  deleteSchema,
  deleteTable,
  deleteVolume,
} from "@/lib/api/catalog";
import { errorMessage } from "@/lib/api/client";
import type { NewColumn } from "@/lib/api/types";

/**
 * One Unity Catalog mutation: runs it, reports it, and refreshes the tree.
 *
 * Every mutation invalidates the whole `["uc"]` key space. Narrower invalidation
 * is tempting but wrong — creating a schema changes the catalog's child list,
 * dropping a catalog invalidates every descendant key, and the tree caches
 * children per expanded node. One prefix keeps them consistent.
 */
function useCatalogMutation<Args extends unknown[]>(
  mutationFn: (...args: Args) => Promise<unknown>,
  // The tuple arrives as one parameter, not spread: a `describe` that only reads
  // the first arg is not assignable to a rest-tuple with optional tail elements.
  // NoInfer keeps `Args` pinned to the mutation's own signature.
  describe: (args: NoInfer<Args>) => string,
): UseMutationResult<unknown, Error, Args> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: Args) => mutationFn(...args),
    onSuccess: (_data, args) => {
      void queryClient.invalidateQueries({ queryKey: ["uc"] });
      toast.success(describe(args));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export function useCatalogMutations() {
  return {
    createCatalog: useCatalogMutation(
      (name: string, comment?: string) => createCatalog(name, comment),
      ([name]) => `Created catalog ${name}`,
    ),
    createSchema: useCatalogMutation(
      (catalog: string, name: string, comment?: string) => createSchema(catalog, name, comment),
      ([catalog, name]) => `Created schema ${catalog}.${name}`,
    ),
    createTable: useCatalogMutation(
      (catalog: string, schema: string, name: string, columns: NewColumn[], comment?: string) =>
        createTable(catalog, schema, name, columns, comment),
      ([catalog, schema, name]) => `Created table ${catalog}.${schema}.${name}`,
    ),
    createVolume: useCatalogMutation(
      (catalog: string, schema: string, name: string, comment?: string) =>
        createVolume(catalog, schema, name, comment),
      ([catalog, schema, name]) => `Created volume ${catalog}.${schema}.${name}`,
    ),
    dropCatalog: useCatalogMutation(
      (name: string) => deleteCatalog(name),
      ([name]) => `Dropped catalog ${name}`,
    ),
    dropSchema: useCatalogMutation(
      (catalog: string, name: string) => deleteSchema(catalog, name),
      ([catalog, name]) => `Dropped schema ${catalog}.${name}`,
    ),
    dropTable: useCatalogMutation(
      (fullName: string) => deleteTable(fullName),
      ([fullName]) => `Dropped table ${fullName}`,
    ),
    dropVolume: useCatalogMutation(
      (fullName: string) => deleteVolume(fullName),
      ([fullName]) => `Dropped volume ${fullName}`,
    ),
  };
}

export type CatalogMutations = ReturnType<typeof useCatalogMutations>;
