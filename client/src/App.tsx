import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { AuthProvider } from './contexts/AuthContext'
import { ReportGenerationProvider } from './contexts/ReportGenerationContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import UserManagementPage from './pages/UserManagementPage'
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
import TimelineComparison from './pages/TimelineComparison'
import ReportPage from './pages/ReportPage'
import AgentPage from './pages/AgentPage'
import EventDetailPage from './pages/EventDetailPage'
import CrossPeriodView from './pages/CrossPeriodView'
import CountryComparison from './pages/CountryComparison'
import MaterialityHeatmap from './pages/MaterialityHeatmap'
import ChatPage from './pages/ChatPage'
import DrilldownPage from './pages/DrilldownPage'
import AlertsPage from './pages/AlertsPage'
import CompetingInfluencePage from './pages/CompetingInfluencePage'
import EntityProfilePage from './pages/EntityProfilePage'
import DataIngestionPage from './pages/DataIngestionPage'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <ReportGenerationProvider>
          <Toaster position="top-right" richColors />
          <Routes>
            {/* All routes are protected by enterprise gateway auth */}
            <Route path="/" element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }>
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
              <Route path="events/:eventId" element={<EventDetailPage />} />
              <Route path="events/:eventId/across-periods" element={<CrossPeriodView />} />
              <Route path="events/comparison" element={<CountryComparison />} />
              <Route path="events/materiality" element={<MaterialityHeatmap />} />
              <Route path="timeline" element={<TimelineComparison />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="report" element={<ReportPage />} />
              <Route path="agent" element={<AgentPage />} />
              <Route path="drilldown" element={<DrilldownPage />} />
              <Route path="alerts" element={<AlertsPage />} />
              <Route path="competing/:recipient" element={<CompetingInfluencePage />} />
              <Route path="entity/:entityId" element={<EntityProfilePage />} />

              {/* Analyst+ routes */}
              <Route path="ingestion" element={
                <ProtectedRoute requiredRole="analyst">
                  <DataIngestionPage />
                </ProtectedRoute>
              } />

              {/* Admin-only routes */}
              <Route path="admin/users" element={
                <ProtectedRoute requiredRole="admin">
                  <UserManagementPage />
                </ProtectedRoute>
              } />
            </Route>
          </Routes>
          </ReportGenerationProvider>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
