import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import Events from './pages/Events'
import Summaries from './pages/Summaries'
import BilateralRelationships from './pages/BilateralRelationships'
import Categories from './pages/Categories'
import InfluencerPage from './pages/InfluencerPage'
import BilateralPage from './pages/BilateralPage'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="documents" element={<Documents />} />
            <Route path="events" element={<Events />} />
            <Route path="summaries" element={<Summaries />} />
            <Route path="bilateral" element={<BilateralRelationships />} />
            <Route path="bilateral/:influencer/:recipient" element={<BilateralPage />} />
            <Route path="categories" element={<Categories />} />
            <Route path="influencer/:country" element={<InfluencerPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
