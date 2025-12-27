import { useQuery } from '@tanstack/react-query'
import { Calendar } from 'lucide-react'
import './Pages.css'

interface Event {
  id: number
  event_name: string
  event_date: string
  initiating_country: string
  recipient_country: string
  category: string
}

export default function Events() {
  const { data, isLoading } = useQuery({
    queryKey: ['events'],
    queryFn: async () => {
      const response = await fetch('/api/events')
      return response.json()
    },
  })

  return (
    <div className="page">
      <header className="page-header">
        <h1>Events</h1>
        <p>Tracked diplomatic events and activities</p>
      </header>

      {isLoading ? (
        <div className="loading">Loading events...</div>
      ) : (
        <div className="cards-grid">
          {data?.events?.length > 0 ? (
            data.events.map((event: Event) => (
              <div key={event.id} className="event-card">
                <div className="event-header">
                  <Calendar size={20} />
                  <span className="event-date">{event.event_date}</span>
                </div>
                <h3>{event.event_name}</h3>
                <div className="event-meta">
                  <span className="badge">{event.category}</span>
                  <span className="countries">
                    {event.initiating_country} → {event.recipient_country}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="empty-state-card">
              <Calendar size={48} />
              <h3>No Events Found</h3>
              <p>Events will appear here once they are tracked in the database.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
