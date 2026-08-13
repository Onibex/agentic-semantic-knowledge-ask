// Copyright (c) 2026 Onibex. All rights reserved.
// Part of Onibex ASK Platform. Source-available under PolyForm Strict 1.0.0 /
// Free Trial 1.0.0 — see LICENSE.md

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
