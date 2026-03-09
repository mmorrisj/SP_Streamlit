import { useNavigate } from 'react-router-dom'
import { useCallback } from 'react'
import type { DrilldownQueryContext, DrilldownChartSelection } from '../api/client'

/**
 * Hook that returns a function to navigate to the drilldown page.
 * Encodes both the original query context and the chart selection into URL params.
 */
export function useDrilldown(queryContext: DrilldownQueryContext) {
  const navigate = useNavigate()

  const openDrilldown = useCallback(
    (selection: DrilldownChartSelection) => {
      const params = new URLSearchParams()

      // Chart selection (what was clicked)
      params.set('dimension', selection.dimension)
      params.set('value', selection.value)
      if (selection.chart_type) params.set('chart_type', selection.chart_type)

      // Original query context (preserved for LLM framing)
      if (queryContext.initiating_country) params.set('init_country', queryContext.initiating_country)
      if (queryContext.recipient_country) params.set('recip_country', queryContext.recipient_country)
      if (queryContext.category) params.set('category', queryContext.category)
      if (queryContext.subcategory) params.set('subcategory', queryContext.subcategory)
      if (queryContext.start_date) params.set('start_date', queryContext.start_date)
      if (queryContext.end_date) params.set('end_date', queryContext.end_date)
      if (queryContext.page_source) params.set('page_source', queryContext.page_source)

      navigate(`/drilldown?${params.toString()}`)
    },
    [navigate, queryContext]
  )

  return openDrilldown
}
