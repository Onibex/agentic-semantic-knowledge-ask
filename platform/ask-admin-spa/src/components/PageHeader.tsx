/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import type { LucideIcon } from 'lucide-react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /**
   * Optional accent icon shown in a tinted rounded square to the left of the
   * title. Mirrors the warmer look the centered admin pages (Workspaces /
   * Organization) use — adopting it here unifies the visual language across
   * full-bleed tools (Merge / History) and form pages.
   */
  icon?: LucideIcon;
  /** Tailwind color suffix for the icon tint (e.g. "blue", "amber"). Default "blue". */
  iconTone?: 'blue' | 'amber' | 'emerald' | 'violet' | 'gray';
  right?: React.ReactNode;
}

const TONE_CLASSES: Record<NonNullable<PageHeaderProps['iconTone']>, string> = {
  blue: 'bg-blue-50 text-blue-600',
  amber: 'bg-amber-50 text-amber-600',
  emerald: 'bg-emerald-50 text-emerald-600',
  violet: 'bg-violet-50 text-violet-600',
  gray: 'bg-gray-100 text-gray-600',
};

export function PageHeader({
  title,
  subtitle,
  icon: Icon,
  iconTone = 'blue',
  right,
}: PageHeaderProps) {
  return (
    <div className="shrink-0 border-b border-gray-200 bg-white px-4 py-2.5 flex items-center gap-3">
      {Icon && (
        <div
          className={`h-8 w-8 rounded-md flex items-center justify-center shrink-0 ${TONE_CLASSES[iconTone]}`}
        >
          <Icon size={16} />
        </div>
      )}
      <div className="min-w-0">
        <h1 className="text-sm font-semibold text-gray-900">{title}</h1>
        {subtitle && <p className="text-[11px] text-gray-500 truncate">{subtitle}</p>}
      </div>
      {right && <div className="ml-auto shrink-0">{right}</div>}
    </div>
  );
}
