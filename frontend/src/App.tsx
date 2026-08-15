import { useState } from 'react'
import { Layout, type Page } from './components/Layout'
import { ComparePage } from './pages/ComparePage'
import { DuplicatesPage } from './pages/DuplicatesPage'

export default function App() {
  const [page, setPage] = useState<Page>('compare')

  return (
    <Layout page={page} onNavigate={setPage}>
      {page === 'compare' ? <ComparePage /> : <DuplicatesPage />}
    </Layout>
  )
}
