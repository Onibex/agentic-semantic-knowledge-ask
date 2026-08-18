/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';

export interface MenuItem {
  label: string;
  onClick: () => void;
  icon?: React.ReactNode;
  tone?: 'default' | 'danger';
  disabled?: boolean;
}

interface MenuDropdownProps {
  items: MenuItem[];
  /** Custom trigger content. Defaults to a ⋯ (MoreHorizontal) icon button. */
  trigger?: React.ReactNode;
  align?: 'left' | 'right';
  buttonClassName?: string;
  title?: string;
}

/**
 * Minimal dependency-free dropdown menu (click-outside + Escape to close).
 *
 * Used for low-frequency / overflow actions so the visible toolbars stay lean:
 * the entity inspector's ⋯ (Remove from domain) and the per-environment ⋯
 * rows (Diff vs dev/prod). Kept hand-rolled because the project's Radix install
 * currently has an unrelated peer-dependency conflict; the menus are simple
 * enough that this is adequate and fully under our control.
 */
export function MenuDropdown({
  items,
  trigger,
  align = 'right',
  buttonClassName,
  title,
}: MenuDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title={title}
        aria-haspopup="menu"
        aria-expanded={open}
        className={
          buttonClassName ??
          'inline-flex items-center rounded px-1.5 py-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition-colors'
        }
      >
        {trigger ?? <MoreHorizontal size={14} />}
      </button>

      {open && (
        <div
          role="menu"
          className={`absolute z-50 mt-1 min-w-[10rem] rounded-md border border-gray-200 bg-white py-1 shadow-lg ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {items.map((it, i) => (
            <button
              key={i}
              role="menuitem"
              disabled={it.disabled}
              onClick={() => {
                setOpen(false);
                it.onClick();
              }}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors disabled:opacity-40 ${
                it.tone === 'danger'
                  ? 'text-rose-600 hover:bg-rose-50'
                  : 'text-gray-700 hover:bg-gray-50'
              }`}
            >
              {it.icon}
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
