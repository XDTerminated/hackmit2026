"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const links = [
  { href: "/", label: "Home", icon: "⌂" },
  { href: "/activity", label: "Activity", icon: "◷" },
  { href: "/device", label: "Device", icon: "◉" },
];

export default function UserShell({ title, headerRight, hideHeaderRight = false, children }: { title: string; headerRight?: ReactNode; hideHeaderRight?: boolean; children: ReactNode }) {
  const path = usePathname();
  return <div className="user-app">
    <div className="user-content">
      <header className="user-header"><span className="user-brand">stride</span>{hideHeaderRight ? null : headerRight ?? <span className="user-header-title">{title}</span>}</header>
      {children}
    </div>
    <nav className="user-nav" aria-label="Primary">
      {links.map((link) => <Link key={link.href} href={link.href} aria-current={path === link.href ? "page" : undefined} className={path === link.href ? "active" : ""}><span className="nav-icon" aria-hidden="true">{link.icon}</span>{link.label}</Link>)}
    </nav>
  </div>;
}
