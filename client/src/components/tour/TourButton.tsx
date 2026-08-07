import { Compass } from 'lucide-react'
import { useTour } from './TourContext'

export default function TourButton() {
  const { startTour } = useTour()
  return (
    <button className="nav-item tour-launch" onClick={startTour}>
      <Compass size={20} />
      <span>Take the tour</span>
    </button>
  )
}
