"use client";

import {
  Clock,
  Database,
  FileCode2,
  Files,
  FolderTree,
  KeyRound,
  NotebookPen,
  PlayCircle,
  Server,
  Settings,
  Star,
  Warehouse,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

const NAV_GROUPS = [
  {
    label: "Query",
    items: [
      { href: "/", label: "Query editor", icon: FileCode2 },
      { href: "/saved-queries", label: "Saved queries", icon: Star },
      { href: "/query-history", label: "Recent queries", icon: Clock },
      { href: "/notebooks", label: "Notebooks", icon: NotebookPen },
    ],
  },
  {
    label: "Data",
    items: [
      { href: "/catalog", label: "Data catalog", icon: Database },
      { href: "/files", label: "Files", icon: Files },
      { href: "/workspace", label: "Workspace", icon: FolderTree },
    ],
  },
  {
    label: "Compute",
    items: [
      { href: "/warehouses", label: "Warehouses", icon: Warehouse },
      { href: "/jobs", label: "Jobs", icon: PlayCircle },
      { href: "/clusters", label: "Clusters", icon: Server },
    ],
  },
  {
    label: "Admin",
    items: [{ href: "/secrets", label: "Secrets", icon: KeyRound }],
  },
] as const;

export function AppSidebar() {
  const pathname = usePathname();

  // `trailingSlash: true` means every route is "/catalog/", so compare on the
  // normalised form rather than on raw equality.
  const current = pathname.replace(/\/+$/, "") || "/";

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <Database className="size-5 shrink-0 text-primary" />
          <span className="truncate font-semibold group-data-[collapsible=icon]:hidden">minilake</span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        {NAV_GROUPS.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      isActive={current === item.href}
                      tooltip={item.label}
                      render={<Link href={item.href} />}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={current === "/settings"}
              tooltip="Settings"
              render={<Link href="/settings" />}
            >
              <Settings />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
