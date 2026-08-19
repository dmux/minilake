"use client";

import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { WarehousePicker } from "@/components/layout/warehouse-picker";
import { Separator } from "@/components/ui/separator";

/**
 * The frame every page renders inside: sidebar, header, and a content area that
 * fills the viewport exactly once (`h-svh` + `min-h-0`), so panes with their own
 * scrollbars — the editor, the result grid — scroll internally instead of
 * growing the page.
 */
export function WorkspaceShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="flex h-svh min-h-0 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
          <SidebarTrigger />
          <Separator orientation="vertical" className="mr-1 h-4" />
          <h1 className="text-sm font-medium">{title}</h1>
          <div className="ml-auto flex items-center gap-2">
            <WarehousePicker />
            <ThemeToggle />
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}
