import axios from 'axios'

export interface Workspace {
  id: string
  slug: string
  name: string
  description?: string
}

export async function listWorkspaces(): Promise<Workspace[]> {
  const { data } = await axios.get<Workspace[]>('/api/admin/workspaces')
  return data
}
