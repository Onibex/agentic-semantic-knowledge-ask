import { Globe } from 'lucide-react'
import { useLocaleStore } from '@/store/localeStore'
import type { Locale } from '@/i18n/translations'

const LANGUAGES: { code: Locale; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'pt', label: 'Português' },
]

export function LanguageSelector() {
  const { locale, setLocale } = useLocaleStore()
  return (
    <div className="flex items-center gap-1.5">
      <Globe size={12} className="shrink-0 text-muted-foreground" />
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        className="flex-1 appearance-none bg-transparent text-xs text-muted-foreground hover:text-foreground focus:outline-none cursor-pointer"
        aria-label="Language"
      >
        {LANGUAGES.map((lang) => (
          <option key={lang.code} value={lang.code}>
            {lang.label}
          </option>
        ))}
      </select>
    </div>
  )
}
