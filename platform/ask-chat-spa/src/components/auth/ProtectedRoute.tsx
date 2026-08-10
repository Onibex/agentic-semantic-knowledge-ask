import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'

interface Props {
  requiredRole?: string
  children: ReactNode
}

export function ProtectedRoute({ requiredRole, children }: Props) {
  const { isLoading, isAuthenticated, user } = useAuthStore()

  // Still initialising
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    )
  }

  // Not authenticated → go to login
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  // Role check
  if (requiredRole && !user?.roles.includes(requiredRole)) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-8 w-full max-w-sm text-center">
          <div className="mb-4 text-amber-500">
            <svg
              className="mx-auto h-12 w-12"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
              />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Access denied</h2>
          <p className="text-sm text-gray-500">
            Your account does not have the <strong>{requiredRole}</strong> role required to access this section.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
