import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { toast } from 'sonner';
import { getStats, exportYamls } from '../api/client';
import type { StatsResponse } from '../api/types';
import { useGraphStore } from '../store/graphStore';
import { useAuthStore } from '../store/authStore';
import { authConfig } from '../auth/config';
import { useTranslation } from '../hooks/useTranslation';

function StatCard({
  title,
  value,
  sub,
  color,
}: {
  title: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 flex flex-col gap-1">
      <span className="text-xs text-gray-500 uppercase tracking-wider">{title}</span>
      <span className={`text-2xl font-bold ${color ?? 'text-gray-800'}`}>{value}</span>
      {sub && <span className="text-xs text-gray-400">{sub}</span>}
    </div>
  );
}

export function HealthPage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      const blob = await exportYamls();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'semantic-layer-export.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(`Export failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setExporting(false);
    }
  }

  const { rawNodes } = useGraphStore();
  const { user, isAuthenticated } = useAuthStore();

  useEffect(() => {
    setLoadingStats(true);
    getStats()
      .then((s) => {
        setStats(s);
        setStatsError(null);
      })
      .catch((err) => {
        setStatsError(String(err));
      })
      .finally(() => setLoadingStats(false));
  }, []);

  const pendingConflictNodes = rawNodes.filter((n) =>
    Array.isArray(n.meta?.conflicts) &&
    n.meta.conflicts.some((c) => {
      const conflict = c as { resolved?: boolean };
      return !conflict.resolved;
    }),
  );

  const byLayer = stats?.by_layer ?? {};

  const layerSub = ['bronze', 'silver', 'gold']
    .filter((l) => byLayer[l] !== undefined)
    .map((l) => `${l}: ${byLayer[l]}`)
    .join(' · ');

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50 p-6">
      <div className="max-w-5xl mx-auto flex flex-col gap-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-800">{t('health_title')}</h1>
          <button
            type="button"
            onClick={() => void handleExport()}
            disabled={exporting}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {exporting ? t('health_exporting') : t('health_export')}
          </button>
        </div>

        {/* Stat cards */}
        {loadingStats ? (
          <div className="flex items-center justify-center py-12">
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-4 border-blue-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-gray-500">{t('health_loading')}</span>
            </div>
          </div>
        ) : statsError ? (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded">
            Failed to load stats: {statsError}
          </div>
        ) : stats ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <StatCard
              title={t('health_stat_total')}
              value={stats.total_yamls}
              sub={layerSub || undefined}
            />
            <StatCard
              title={t('health_stat_conflicts')}
              value={stats.pending_conflicts}
              color={stats.pending_conflicts > 0 ? 'text-amber-600' : 'text-green-600'}
            />
            <StatCard
              title={t('health_stat_recent')}
              value={stats.recently_updated}
              sub={t('health_stat_recent_sub')}
            />
          </div>
        ) : null}

        {/* Pending Conflicts */}
        <section>
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
            {t('health_conflicts_title')}
          </h2>
          {pendingConflictNodes.length === 0 ? (
            <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded-lg px-4 py-3">
              {t('health_no_conflicts')}
            </p>
          ) : (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="text-left px-4 py-2 font-medium text-gray-600">{t('health_col_name')}</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600">{t('health_col_layer')}</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600">{t('health_col_unresolved')}</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600">{t('health_col_action')}</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingConflictNodes.map((n) => {
                    const unresolved = (n.meta?.conflicts ?? []).filter(
                      (c) => !(c as { resolved?: boolean }).resolved,
                    ).length;
                    return (
                    <tr key={n.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-800 font-medium">{n.name}</td>
                      <td className="px-4 py-2 text-gray-500 capitalize">{n.layer}</td>
                      <td className="px-4 py-2 text-amber-700 font-medium">{unresolved}</td>
                      <td className="px-4 py-2">
                        <NavLink
                          to="/semantic-knowledge?status=conflicts"
                          className="text-blue-600 hover:text-blue-800 text-xs font-medium"
                        >
                          {t('health_resolve')}
                        </NavLink>
                      </td>
                    </tr>
                  );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Auth Status */}
        <section>
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
            {t('health_auth_title')}
          </h2>
          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
            <div className="px-4 py-3 flex items-center justify-between">
              <span className="text-sm text-gray-500">{t('health_idp_mode')}</span>
              <span className={`text-sm font-medium px-2 py-0.5 rounded-full ${
                authConfig.mode === 'none'
                  ? 'bg-gray-100 text-gray-600'
                  : authConfig.mode === 'keycloak'
                  ? 'bg-blue-100 text-blue-700'
                  : 'bg-violet-100 text-violet-700'
              }`}>
                {authConfig.mode === 'none'
                  ? 'dev bypass (none)'
                  : authConfig.mode === 'keycloak'
                  ? 'SSO'
                  : authConfig.mode}
              </span>
            </div>
            {authConfig.mode !== 'none' && (
              <div className="px-4 py-3 flex items-start justify-between gap-4">
                <span className="text-sm text-gray-500 shrink-0">Issuer</span>
                <span className="text-sm text-gray-700 font-mono text-right break-all">
                  {authConfig.issuerUrl || '—'}
                </span>
              </div>
            )}
            <div className="px-4 py-3 flex items-center justify-between">
              <span className="text-sm text-gray-500">Session</span>
              {isAuthenticated ? (
                <span className="text-sm font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
                  Authenticated
                </span>
              ) : (
                <span className="text-sm font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
                  Not authenticated
                </span>
              )}
            </div>
            {user && (
              <>
                <div className="px-4 py-3 flex items-center justify-between">
                  <span className="text-sm text-gray-500">User</span>
                  <span className="text-sm text-gray-800">{user.email}</span>
                </div>
                <div className="px-4 py-3 flex items-start justify-between gap-4">
                  <span className="text-sm text-gray-500 shrink-0">Roles</span>
                  <div className="flex flex-wrap gap-1 justify-end">
                    {user.roles.length > 0 ? user.roles.map((r) => (
                      <span key={r} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-mono">
                        {r}
                      </span>
                    )) : (
                      <span className="text-sm text-gray-400">—</span>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
