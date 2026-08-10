export interface AuthConfig {
  mode: 'keycloak' | 'xsuaa' | 'none'
  issuerUrl: string
  authorizationEndpoint: string
  tokenEndpoint: string
  /** RP-initiated logout (end-session) endpoint — terminates the IdP SSO session. */
  endSessionEndpoint: string
  clientId: string
  redirectUri: string
  scopes: string[]
}

function buildKeycloakConfig(): AuthConfig {
  const baseUrl = import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8180'
  const realm = import.meta.env.VITE_KEYCLOAK_REALM ?? 'ask-platform'
  const clientId = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? 'ask-setup-spa'
  const issuerUrl = `${baseUrl}/realms/${realm}`

  return {
    mode: 'keycloak',
    issuerUrl,
    authorizationEndpoint: `${issuerUrl}/protocol/openid-connect/auth`,
    tokenEndpoint: `${issuerUrl}/protocol/openid-connect/token`,
    endSessionEndpoint: `${issuerUrl}/protocol/openid-connect/logout`,
    clientId,
    redirectUri: `${window.location.origin}/login/callback`,
    scopes: ['openid', 'profile', 'email'],
  }
}

function buildXsuaaConfig(): AuthConfig {
  const baseUrl = import.meta.env.VITE_XSUAA_URL ?? ''
  const clientId = import.meta.env.VITE_XSUAA_CLIENT_ID ?? ''

  return {
    mode: 'xsuaa',
    issuerUrl: baseUrl,
    authorizationEndpoint: `${baseUrl}/oauth/authorize`,
    tokenEndpoint: `${baseUrl}/oauth/token`,
    endSessionEndpoint: `${baseUrl}/logout`,
    clientId,
    redirectUri: `${window.location.origin}/login/callback`,
    scopes: ['openid'],
  }
}

function buildNoneConfig(): AuthConfig {
  return {
    mode: 'none',
    issuerUrl: '',
    authorizationEndpoint: '',
    tokenEndpoint: '',
    endSessionEndpoint: '',
    clientId: '',
    redirectUri: `${window.location.origin}/login/callback`,
    scopes: [],
  }
}

function resolveAuthConfig(): AuthConfig {
  const authMode = import.meta.env.VITE_AUTH_MODE

  if (authMode === 'keycloak') {
    return buildKeycloakConfig()
  }

  if (authMode === 'xsuaa') {
    return buildXsuaaConfig()
  }

  // VITE_AUTH_MODE unset / unknown → dev bypass (no login)
  return buildNoneConfig()
}

export const authConfig: AuthConfig = resolveAuthConfig()
