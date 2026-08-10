import {
  ArrowRight,
  BookOpen,
  Building2,
  CheckCircle2,
  ExternalLink,
  GitBranch,
  Layers,
  Library,
  MessagesSquare,
  Rocket,
  Settings2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/hooks/useTranslation'

const REPO_GUIDE_URL = 'https://github.com/Onibex/agentic-semantic-knowledge-ask/tree/main/platform'

// Non-translatable config — icons + routes only
const STEP_ICONS: LucideIcon[] = [Settings2, Layers, GitBranch, MessagesSquare]

const TASK_CONFIG: { icon: LucideIcon; to: string }[] = [
  { icon: Building2, to: '/workspaces' },
  { icon: Library,   to: '/semantic-knowledge' },
  { icon: Building2, to: '/organization' },
  { icon: Settings2, to: '/admin/setup' },
  { icon: BookOpen,  to: '/admin/docs' },
]

export default function GettingStartedPage() {
  const { t } = useTranslation()

  const STEPS = [
    { n: 1, icon: STEP_ICONS[0], title: t('gs_step1_title'), where: t('gs_step1_where'), desc: t('gs_step1_desc') },
    { n: 2, icon: STEP_ICONS[1], title: t('gs_step2_title'), where: t('gs_step2_where'), desc: t('gs_step2_desc') },
    { n: 3, icon: STEP_ICONS[2], title: t('gs_step3_title'), where: t('gs_step3_where'), desc: t('gs_step3_desc') },
    { n: 4, icon: STEP_ICONS[3], title: t('gs_step4_title'), where: t('gs_step4_where'), desc: t('gs_step4_desc') },
  ]

  const TASKS = TASK_CONFIG.map((cfg, i) => ({
    ...cfg,
    label: t(`gs_task${i + 1}_title` as Parameters<typeof t>[0]),
    desc:  t(`gs_task${i + 1}_desc`  as Parameters<typeof t>[0]),
  }))

  const TERMS = [
    { term: t('gs_term_workspace'), def: t('gs_term_workspace_desc') },
    { term: t('gs_term_domain'),    def: t('gs_term_domain_desc') },
    { term: t('gs_term_product'),   def: t('gs_term_product_desc') },
    { term: t('gs_term_layers'),    def: t('gs_term_layers_desc') },
    { term: t('gs_term_publish'),   def: t('gs_term_publish_desc') },
    { term: t('gs_term_mode'),      def: t('gs_term_mode_desc') },
  ]

  return (
    <div className="max-w-5xl mx-auto p-6 pb-16">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-8">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
            <Rocket size={20} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">{t('gs_title')}</h1>
            <p className="text-sm text-gray-500 mt-1 max-w-2xl">{t('gs_subtitle')}</p>
          </div>
        </div>
        <a href={REPO_GUIDE_URL} target="_blank" rel="noreferrer" className="shrink-0">
          <Button variant="outline" size="sm">
            <BookOpen size={14} className="mr-1.5" />
            {t('gs_full_guide')}
            <ExternalLink size={12} className="ml-1.5 opacity-60" />
          </Button>
        </a>
      </div>

      {/* The journey */}
      <section className="mb-10">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
          {t('gs_how_it_works')}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {STEPS.map((s) => {
            const Icon = s.icon
            return (
              <div
                key={s.n}
                className="relative bg-white border border-gray-200 rounded-lg p-4 flex flex-col"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="h-6 w-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center shrink-0">
                    {s.n}
                  </span>
                  <Icon size={16} className="text-blue-600" />
                </div>
                <p className="text-sm font-semibold text-gray-900">{s.title}</p>
                <p className="text-[11px] font-medium text-blue-600/80 mb-1">{s.where}</p>
                <p className="text-xs text-gray-500 leading-relaxed">{s.desc}</p>
              </div>
            )
          })}
        </div>

        <div className="mt-3 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <CheckCircle2 size={16} className="text-amber-600 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-900 leading-relaxed">{t('gs_warning')}</p>
        </div>
      </section>

      {/* Admin checklist */}
      <section className="mb-10">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
          {t('gs_setup_layer')}
        </h2>
        <div className="space-y-2">
          {TASKS.map((task) => {
            const Icon = task.icon
            return (
              <Link
                key={task.to + task.label}
                to={task.to}
                className="group flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 hover:border-blue-300 hover:bg-blue-50/40 transition-colors"
              >
                <div className="h-8 w-8 rounded-md bg-gray-100 group-hover:bg-blue-100 flex items-center justify-center shrink-0 transition-colors">
                  <Icon size={16} className="text-gray-600 group-hover:text-blue-600" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">{task.label}</p>
                  <p className="text-xs text-gray-500 truncate">{task.desc}</p>
                </div>
                <ArrowRight size={16} className="text-gray-300 group-hover:text-blue-500 shrink-0 transition-colors" />
              </Link>
            )
          })}
        </div>
        <p className="mt-2 text-xs text-gray-400">{t('gs_footer')}</p>
      </section>

      {/* How users ask */}
      <section className="mb-10">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
          {t('gs_how_users_ask')}
        </h2>
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-start gap-3">
            <div className="h-8 w-8 rounded-md bg-blue-50 flex items-center justify-center shrink-0">
              <MessagesSquare size={16} className="text-blue-600" />
            </div>
            <div className="text-sm text-gray-600 leading-relaxed">
              {t('gs_users_ask_desc')}
            </div>
          </div>
        </div>
      </section>

      {/* Key concepts */}
      <section className="mb-10">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
          {t('gs_key_concepts')}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 rounded-lg border border-gray-200 bg-white p-5">
          {TERMS.map((term) => (
            <div key={term.term}>
              <p className="text-sm font-semibold text-gray-900">{term.term}</p>
              <p className="text-xs text-gray-500 leading-relaxed">{term.def}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 px-5 py-4">
        <div>
          <p className="text-sm font-medium text-gray-900">{t('gs_footer_walkthrough')}</p>
          <p className="text-xs text-gray-500">{t('gs_footer_walkthrough_desc')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/workspaces">
            <Button variant="outline" size="sm">
              {t('gs_footer_start_workspaces')}
              <ArrowRight size={14} className="ml-1.5" />
            </Button>
          </Link>
          <a href={REPO_GUIDE_URL} target="_blank" rel="noreferrer">
            <Button size="sm">
              <BookOpen size={14} className="mr-1.5" />
              {t('gs_full_guide')}
            </Button>
          </a>
        </div>
      </div>
    </div>
  )
}
