/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useState } from 'react';
import { useHistoryStore } from '../../store/historyStore';
import { useAuthStore } from '../../store/authStore';

export function RestoreDialog() {
  const {
    restoreDialogOpen,
    restoreTarget,
    restoring,
    restoreError,
    closeRestoreDialog,
    confirmRestore,
  } = useHistoryStore();
  const email = useAuthStore((s) => s.user?.email ?? null);

  const [reason, setReason] = useState('');

  if (!restoreDialogOpen || !restoreTarget) return null;

  const shortSha = restoreTarget.slice(0, 7);

  function handleConfirm() {
    void confirmRestore(reason.trim() || undefined);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-800">Restore to previous version</h2>
        </div>

        {/* Body */}
        <div className="px-5 py-4 flex flex-col gap-3">
          <p className="text-sm text-gray-600">
            This will create a new commit restoring this YAML to version{' '}
            <span className="font-mono font-medium bg-gray-100 px-1 rounded">{shortSha}</span>.
          </p>

          <div className="text-xs text-gray-500">
            Author: <span className="font-medium text-gray-700">{email ?? 'dev session'}</span>
            <span className="ml-1 text-gray-400">(from your login)</span>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Reason (optional)</label>
            <input
              type="text"
              placeholder="e.g. Reverting incorrect field removal"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="text-xs border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
            />
          </div>

          {restoreError && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">
              {restoreError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-end gap-2">
          <button
            onClick={closeRestoreDialog}
            disabled={restoring}
            className="text-xs font-medium text-gray-600 border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={restoring}
            className="text-xs font-medium bg-blue-600 text-white rounded px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {restoring && (
              <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            {restoring ? 'Restoring…' : 'Confirm restore'}
          </button>
        </div>
      </div>
    </div>
  );
}
