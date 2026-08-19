/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// ── Field ─────────────────────────────────────────────────────────────────────

interface FieldProps {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  disabled?: boolean
}

export function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  disabled,
}: FieldProps) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete={type === 'password' ? 'new-password' : undefined}
      />
    </div>
  )
}

// ── cleanSection ──────────────────────────────────────────────────────────────

/**
 * Strip blank password/secret fields from a config section before saving,
 * so the backend keeps the existing secret instead of overwriting with "".
 */
export function cleanSection<T extends object>(
  current: T,
  passwordFields: (keyof T)[],
): T {
  const out = { ...(current as unknown as Record<string, unknown>) }
  for (const field of passwordFields) {
    if (!out[field as string]) {
      delete out[field as string]
    }
  }
  return out as unknown as T
}

// ── LoadingState + ErrorState ────────────────────────────────────────────────

export function LoadingState({ label }: { label?: string }) {
  return (
    <div className="p-8 flex items-center gap-3 text-gray-500">
      <div className="h-5 w-5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
      <span>{label ?? 'Loading…'}</span>
    </div>
  )
}

export function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string
  message: string
  onRetry: () => void
}) {
  return (
    <div className="p-8">
      <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 max-w-lg">
        <p className="font-medium mb-1">{title}</p>
        <p>{message}</p>
        <button
          className="mt-2 text-red-600 underline text-xs"
          onClick={onRetry}
        >
          Retry
        </button>
      </div>
    </div>
  )
}
