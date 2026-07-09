"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  CheckSquareIcon,
  ListChecksIcon,
  MessageSquareIcon,
  TerminalIcon,
  WorkflowIcon,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuItem,
  SidebarProvider,
} from "@/components/ui/sidebar"
import { cn } from "@/lib/utils"

const navItems = [
  { href: "/", label: "Command Approvals", icon: CheckSquareIcon },
  { href: "/sessions", label: "Sessions", icon: MessageSquareIcon },
  { href: "/runs", label: "Runs", icon: ListChecksIcon },
  { href: "/commands", label: "Command Records", icon: TerminalIcon },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  return (
    <SidebarProvider>
      <Sidebar collapsible="none" className="border-r">
        <SidebarHeader className="p-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <WorkflowIcon />
            </span>
            <span>Mica AgentOps</span>
          </Link>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Control Plane</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {navItems.map((item) => {
                  const isActive = isActiveRoute(pathname, item.href)
                  const Icon = item.icon
                  return (
                    <SidebarMenuItem key={item.href}>
                      <Link
                        href={item.href}
                        className={cn(
                          "flex h-8 items-center gap-2 rounded-md px-2 text-sm transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                          isActive && "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                        )}
                      >
                        <Icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center justify-between border-b bg-background px-6">
          <div>
            <p className="text-sm font-medium">Mica AgentOps</p>
            <p className="text-xs text-muted-foreground">Policy-gated command execution</p>
          </div>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}

function isActiveRoute(pathname: string, href: string) {
  if (href === "/") return pathname === "/" || pathname === "/approvals"
  if (href === "/sessions") return pathname === "/sessions" || pathname.startsWith("/sessions/")
  if (href === "/runs") return pathname === "/runs" || pathname.startsWith("/runs/")
  return pathname === href
}
