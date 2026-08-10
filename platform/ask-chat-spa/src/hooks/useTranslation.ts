import { useLocaleStore } from '@/store/localeStore'
import { translations, type TranslationKey } from '@/i18n/translations'

export function useTranslation() {
  const locale = useLocaleStore((s) => s.locale)
  const t = (key: TranslationKey): string =>
    translations[locale]?.[key] ?? translations.en[key] ?? key
  return { t, locale }
}
