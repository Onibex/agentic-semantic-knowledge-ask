/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useId } from 'react'

interface OnibexLogoProps {
  className?: string
  animated?: boolean
}

export function OnibexLogo({ className, animated = true }: OnibexLogoProps) {
  // Unique filter ID so multiple instances on the same page don't conflict.
  const uid = useId().replace(/[^a-z0-9]/gi, '')
  const filterId = `onibex-f-${uid}`

  return (
    <svg
      viewBox="0 0 100 108"
      overflow="visible"            /* let glow bleed past the SVG boundary */
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Onibex"
    >
      {animated && (
        <defs>
          {/*
            feGaussianBlur in="SourceGraphic" blurs the actual rendered pixels
            (the navy logo shapes). Because the corners of the bounding box are
            transparent, the blur only spreads from where the logo pixels are,
            so the glow follows the octagonal silhouette instead of a rectangle.

            feColorMatrix then recolors the navy blur to #60a5fa blue and
            amplifies the alpha slightly so the halo is vivid but still soft.
          */}
          <filter
            id={filterId}
            x="-80%"
            y="-80%"
            width="260%"
            height="260%"
          >
            {/* Tight inner glow — hugs the shape edges */}
            <feGaussianBlur in="SourceGraphic" result="blurTight">
              <animate
                attributeName="stdDeviation"
                values="3;8;3"
                dur="3s"
                repeatCount="indefinite"
                calcMode="spline"
                keyTimes="0;0.5;1"
                keySplines="0.4 0 0.6 1;0.4 0 0.6 1"
              />
            </feGaussianBlur>

            {/* Wide outer halo — broad, faint bloom */}
            <feGaussianBlur in="SourceGraphic" result="blurWide">
              <animate
                attributeName="stdDeviation"
                values="6;16;6"
                dur="3s"
                repeatCount="indefinite"
                calcMode="spline"
                keyTimes="0;0.5;1"
                keySplines="0.4 0 0.6 1;0.4 0 0.6 1"
              />
            </feGaussianBlur>

            {/* Recolor tight blur → bright blue-300, alpha ×6 */}
            <feColorMatrix
              in="blurTight"
              type="matrix"
              result="glowTight"
              values="0 0 0 0 0.580
                      0 0 0 0 0.769
                      0 0 0 0 0.992
                      0 0 0 6 0"
            />

            {/* Recolor wide blur → deeper blue-500, alpha ×3 */}
            <feColorMatrix
              in="blurWide"
              type="matrix"
              result="glowWide"
              values="0 0 0 0 0.235
                      0 0 0 0 0.510
                      0 0 0 0 0.965
                      0 0 0 3 0"
            />

            {/* wide halo → tight glow (×3) → original on top */}
            <feMerge>
              <feMergeNode in="glowWide" />
              <feMergeNode in="glowWide" />
              <feMergeNode in="glowTight" />
              <feMergeNode in="glowTight" />
              <feMergeNode in="glowTight" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
      )}

      <g filter={animated ? `url(#${filterId})` : undefined} fill="#0D2B6E">
        {/* Connector tab */}
        <rect x="42" y="0" width="16" height="14" rx="3" ry="3" />

        {/* Octagonal ring: outer chamfered-rect − rounded-rect inner hole */}
        <path
          fillRule="evenodd"
          d="
            M 28,13 L 72,13 L 95,36 L 95,76 L 72,99 L 28,99 L 5,76 L 5,36 Z

            M 34,31
            L 66,31 A 11,11 0 0,1 77,42
            L 77,70 A 11,11 0 0,1 66,81
            L 34,81 A 11,11 0 0,1 23,70
            L 23,42 A 11,11 0 0,1 34,31 Z
          "
        />
      </g>
    </svg>
  )
}
