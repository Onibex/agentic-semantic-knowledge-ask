import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { LoadingState, ErrorState } from '@/lib/form-helpers'
import { getConfig, saveConfig, testDatabaseConnection } from '@/api/client'
import type { HanaConfig, PostgresConfig, DatabaseTestResult } from '@/api/types'
import { useTranslation } from '@/hooks/useTranslation'

// ── Types ─────────────────────────────────────────────────────────────────────

type DbType = 'hana' | 'postgresql'
type Env = 'dev' | 'prod'

interface HanaForm {
  host: string
  port: number
  user: string
  password: string
  schema: string
}

interface PgForm {
  host: string
  port: number
  database: string
  user: string
  password: string
  sslmode: string
}

const EMPTY_HANA: HanaForm = { host: '', port: 443, user: '', password: '', schema: '' }
const EMPTY_PG: PgForm = { host: '', port: 5432, database: '', user: '', password: '', sslmode: 'prefer' }
const SSL_MODES = ['prefer', 'disable', 'require', 'allow'] as const

function isHanaComplete(f: HanaForm) {
  return !!(f.host && f.user && f.password)
}

function isPgComplete(f: PgForm) {
  return !!(f.host && f.database && f.user && f.password)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TestResultBanner({ result }: { result: DatabaseTestResult }) {
  const { t } = useTranslation()
  return (
    <div
      className={`rounded-md px-4 py-2.5 text-sm max-w-lg ${
        result.ok
          ? 'bg-green-50 border border-green-200 text-green-800'
          : 'bg-red-50 border border-red-200 text-red-800'
      }`}
    >
      <span className="font-medium">{result.ok ? t('db_connected') : t('db_connection_failed')}:</span>{' '}
      {result.message}
    </div>
  )
}

function HanaFields({ form, onChange, disabled }: {
  form: HanaForm
  onChange: (f: HanaForm) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="col-span-2 space-y-1.5">
        <Label htmlFor="hana-host">{t('db_hana_host_label')}</Label>
        <Input
          id="hana-host"
          value={form.host}
          onChange={(e) => onChange({ ...form, host: e.target.value })}
          placeholder="myinstance.hanacloud.ondemand.com"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="hana-port">{t('db_port_label')}</Label>
        <Input
          id="hana-port"
          type="number"
          value={String(form.port)}
          onChange={(e) => onChange({ ...form, port: Number(e.target.value) || 443 })}
          placeholder="443"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="hana-schema">{t('db_hana_schema_label')}</Label>
        <Input
          id="hana-schema"
          value={form.schema}
          onChange={(e) => onChange({ ...form, schema: e.target.value })}
          placeholder="MY_SCHEMA"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="hana-user">{t('db_user_label')}</Label>
        <Input
          id="hana-user"
          value={form.user}
          onChange={(e) => onChange({ ...form, user: e.target.value })}
          placeholder="DBADMIN"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="hana-password">{t('db_password_label')}</Label>
        <Input
          id="hana-password"
          type="password"
          value={form.password}
          onChange={(e) => onChange({ ...form, password: e.target.value })}
          placeholder={t('db_password_ph')}
          disabled={disabled}
        />
      </div>
    </div>
  )
}

function PgFields({ form, onChange, disabled }: {
  form: PgForm
  onChange: (f: PgForm) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="col-span-2 space-y-1.5">
        <Label htmlFor="pg-host">{t('db_pg_host_label')}</Label>
        <Input
          id="pg-host"
          value={form.host}
          onChange={(e) => onChange({ ...form, host: e.target.value })}
          placeholder="12.34.56.78"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pg-port">{t('db_port_label')}</Label>
        <Input
          id="pg-port"
          type="number"
          value={String(form.port)}
          onChange={(e) => onChange({ ...form, port: Number(e.target.value) || 5432 })}
          placeholder="5432"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pg-database">{t('db_pg_database_label')}</Label>
        <Input
          id="pg-database"
          value={form.database}
          onChange={(e) => onChange({ ...form, database: e.target.value })}
          placeholder="mydb"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pg-user">{t('db_user_label')}</Label>
        <Input
          id="pg-user"
          value={form.user}
          onChange={(e) => onChange({ ...form, user: e.target.value })}
          placeholder="dbuser"
          disabled={disabled}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pg-password">{t('db_password_label')}</Label>
        <Input
          id="pg-password"
          type="password"
          value={form.password}
          onChange={(e) => onChange({ ...form, password: e.target.value })}
          placeholder={t('db_password_ph')}
          disabled={disabled}
        />
      </div>
      <div className="col-span-2 space-y-1.5">
        <Label>{t('db_ssl_mode_label')}</Label>
        <div className="flex gap-2 flex-wrap">
          {SSL_MODES.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => onChange({ ...form, sslmode: m })}
              disabled={disabled}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                form.sslmode === m
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Per-environment panel ─────────────────────────────────────────────────────

function EnvPanel({
  env,
  dbType,
  hana,
  pg,
  onHanaChange,
  onPgChange,
}: {
  env: Env
  dbType: DbType
  hana: HanaForm
  pg: PgForm
  onHanaChange: (f: HanaForm) => void
  onPgChange: (f: PgForm) => void
}) {
  const { t } = useTranslation()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<DatabaseTestResult | null>(null)

  const isComplete = dbType === 'hana' ? isHanaComplete(hana) : isPgComplete(pg)

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const cfg: Partial<HanaConfig> | Partial<PostgresConfig> =
        dbType === 'hana'
          ? { host: hana.host, port: hana.port, user: hana.user, password: hana.password, schema: hana.schema || undefined }
          : { host: pg.host, port: pg.port, database: pg.database, user: pg.user, password: pg.password, sslmode: pg.sslmode }
      const result = await testDatabaseConnection({ db_type: dbType, config: cfg })
      setTestResult(result)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Connection test failed'
      setTestResult({ ok: false, message: msg })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-xs text-gray-500">
        {env === 'dev' ? t('db_dev_desc') : t('db_prod_desc')}
      </p>

      {dbType === 'hana' ? (
        <HanaFields form={hana} onChange={onHanaChange} />
      ) : (
        <PgFields form={pg} onChange={onPgChange} />
      )}

      <div className="space-y-2 pt-1">
        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleTest()}
          disabled={testing || !isComplete}
          className="min-w-44"
        >
          {testing ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              {t('db_testing')}
            </>
          ) : (
            t('db_test_btn').replace('{env}', env)
          )}
        </Button>
        {!isComplete && (
          <p className="text-xs text-gray-400">{t('db_fill_required')}</p>
        )}
        {testResult && <TestResultBanner result={testResult} />}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DatabasePage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [activeTab, setActiveTab] = useState<Env>('dev')

  const [dbType, setDbType] = useState<DbType>('postgresql')

  const [devHana, setDevHana] = useState<HanaForm>(EMPTY_HANA)
  const [devPg, setDevPg] = useState<PgForm>(EMPTY_PG)
  const [prodHana, setProdHana] = useState<HanaForm>(EMPTY_HANA)
  const [prodPg, setProdPg] = useState<PgForm>(EMPTY_PG)

  useEffect(() => {
    void loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function extractHana(block: Record<string, unknown> | undefined): HanaForm {
    if (!block) return EMPTY_HANA
    return {
      host: String(block.host ?? ''),
      port: Number(block.port ?? 443),
      user: String(block.user ?? ''),
      password: '',
      schema: String(block.schema ?? ''),
    }
  }

  function extractPg(block: Record<string, unknown> | undefined): PgForm {
    if (!block) return EMPTY_PG
    return {
      host: String(block.host ?? ''),
      port: Number(block.port ?? 5432),
      database: String(block.database ?? ''),
      user: String(block.user ?? ''),
      password: '',
      sslmode: String(block.sslmode ?? 'prefer'),
    }
  }

  async function loadConfig() {
    setLoading(true)
    setLoadError(null)
    try {
      const cfg = await getConfig()
      const savedType: DbType = cfg.db_type ?? 'postgresql'
      setDbType(savedType)

      const envs = (cfg.environments ?? {}) as Record<string, Record<string, unknown>>
      const devBlock = envs.dev ?? {}
      const prodBlock = envs.prod ?? {}

      // dev: prefer environments.dev.{db_type}, fall back to top-level
      const devHanaRaw = (devBlock.hana ?? cfg.hana) as Record<string, unknown> | undefined
      const devPgRaw = (devBlock.postgresql ?? cfg.postgresql) as Record<string, unknown> | undefined
      setDevHana(extractHana(devHanaRaw))
      setDevPg(extractPg(devPgRaw))

      const prodHanaRaw = prodBlock.hana as Record<string, unknown> | undefined
      const prodPgRaw = prodBlock.postgresql as Record<string, unknown> | undefined
      setProdHana(extractHana(prodHanaRaw))
      setProdPg(extractPg(prodPgRaw))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error loading configuration'
      setLoadError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    const devComplete = dbType === 'hana' ? isHanaComplete(devHana) : isPgComplete(devPg)
    if (!devComplete) {
      toast.error(dbType === 'postgresql' ? t('db_dev_incomplete_pg') : t('db_dev_incomplete_hana'))
      return
    }

    setSaving(true)
    try {
      const devCfg = dbType === 'hana'
        ? { host: devHana.host, port: devHana.port, user: devHana.user, ...(devHana.password ? { password: devHana.password } : {}), ...(devHana.schema ? { schema: devHana.schema } : {}) }
        : { host: devPg.host, port: devPg.port, database: devPg.database, user: devPg.user, ...(devPg.password ? { password: devPg.password } : {}), sslmode: devPg.sslmode }

      const prodComplete = dbType === 'hana' ? isHanaComplete(prodHana) : isPgComplete(prodPg)
      const prodCfg = prodComplete
        ? dbType === 'hana'
          ? { host: prodHana.host, port: prodHana.port, user: prodHana.user, ...(prodHana.password ? { password: prodHana.password } : {}), ...(prodHana.schema ? { schema: prodHana.schema } : {}) }
          : { host: prodPg.host, port: prodPg.port, database: prodPg.database, user: prodPg.user, ...(prodPg.password ? { password: prodPg.password } : {}), sslmode: prodPg.sslmode }
        : null

      const environments: Record<string, unknown> = {
        dev: { db_type: dbType, [dbType]: devCfg },
      }
      if (prodCfg) {
        environments.prod = { db_type: dbType, [dbType]: prodCfg }
      }

      const result = await saveConfig({
        db_type: dbType,
        [dbType]: devCfg,      // mirror dev into legacy top-level block
        environments,
      })

      if (result.success) {
        toast.success('Database configuration saved')
      } else {
        toast.error(result.message ?? 'Error saving configuration')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error saving configuration'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return <LoadingState label={t('db_loading')} />
  }

  if (loadError) {
    return (
      <ErrorState
        title={t('db_error_loading')}
        message={loadError}
        onRetry={() => void loadConfig()}
      />
    )
  }

  const prodComplete = dbType === 'hana' ? isHanaComplete(prodHana) : isPgComplete(prodPg)

  return (
    <div className="p-8 max-w-3xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{t('db_title')}</h1>
        <p className="text-sm text-gray-500 mt-1">{t('db_subtitle')}</p>
      </div>

      {/* Engine selector */}
      <div className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
          {t('db_engine_label')}
        </p>
        <div className="flex gap-2">
          {(['postgresql', 'hana'] as const).map((dbT) => (
            <button
              key={dbT}
              type="button"
              onClick={() => setDbType(dbT)}
              className={`px-4 py-2 rounded-md text-sm font-medium border transition-colors ${
                dbType === dbT
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:border-gray-400'
              }`}
            >
              {dbT === 'postgresql' ? 'PostgreSQL' : 'SAP HANA Cloud'}
            </button>
          ))}
        </div>
      </div>

      {/* Env tabs */}
      <div className="border rounded-md overflow-hidden">
        {/* Tab headers */}
        <div className="flex border-b bg-gray-50">
          {(['dev', 'prod'] as const).map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => setActiveTab(e)}
              className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors ${
                activeTab === e
                  ? 'bg-white text-blue-700 border-b-2 border-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {e === 'dev' ? t('db_dev_tab') : t('db_prod_tab')}
              {e === 'prod' && !prodComplete && (
                <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-amber-400 align-middle" />
              )}
            </button>
          ))}
        </div>

        {/* Tab body */}
        <div className="p-5">
          {activeTab === 'dev' ? (
            <EnvPanel
              env="dev"
              dbType={dbType}
              hana={devHana}
              pg={devPg}
              onHanaChange={setDevHana}
              onPgChange={setDevPg}
            />
          ) : (
            <EnvPanel
              env="prod"
              dbType={dbType}
              hana={prodHana}
              pg={prodPg}
              onHanaChange={setProdHana}
              onPgChange={setProdPg}
            />
          )}
        </div>
      </div>

      {/* Prod warning */}
      {!prodComplete && (
        <p className="mt-3 text-xs text-amber-600">{t('db_prod_empty_warning')}</p>
      )}

      {/* Save */}
      <div className="mt-6">
        <Button onClick={() => void handleSave()} disabled={saving} className="min-w-48">
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t('common_saving')}
            </>
          ) : (
            t('db_save_btn')
          )}
        </Button>
      </div>
    </div>
  )
}
