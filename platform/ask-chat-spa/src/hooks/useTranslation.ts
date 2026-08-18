/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useLocaleStore } from '@/store/localeStore'
import { translations, type TranslationKey } from '@/i18n/translations'

export function useTranslation() {
  const locale = useLocaleStore((s) => s.locale)
  const t = (key: TranslationKey): string =>
    translations[locale]?.[key] ?? translations.en[key] ?? key
  return { t, locale }
}
