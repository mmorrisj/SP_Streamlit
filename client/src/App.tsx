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
import OverallMetrics from './pages/OverallMetrics'
import InfluencerMetricsPage from './pages/InfluencerMetricsPage'
import BilateralMetricsPage from './pages/BilateralMetricsPage'
import RecipientMetricsPage from './pages/RecipientMetricsPage'
import DocumentSummariesPage from './pages/DocumentSummariesPage'
import SummaryDetailPage from './pages/SummaryDetailPage'
import BilateralSummariesPage from './pages/BilateralSummariesPage'
import BilateralSummaryDetailPage from './pages/BilateralSummaryDetailPage'

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
            <Route path="document-summaries" element={<DocumentSummariesPage />} />
            <Route path="document-summaries/detail" element={<SummaryDetailPage />} />
            <Route path="bilateral-summaries" element={<BilateralSummariesPage />} />
            <Route path="bilateral-summaries/detail" element={<BilateralSummaryDetailPage />} />
            <Route path="bilateral" element={<BilateralRelationships />} />
            <Route path="bilateral/:influencer/:recipient" element={<BilateralPage />} />
            <Route path="bilateral-metrics/:influencer/:recipient" element={<BilateralMetricsPage />} />
            <Route path="categories" element={<Categories />} />
            <Route path="influencer/:country" element={<InfluencerPage />} />
            <Route path="metrics" element={<OverallMetrics />} />
            <Route path="metrics/influencer/:country" element={<InfluencerMetricsPage />} />
            <Route path="metrics/recipient/:country" element={<RecipientMetricsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
