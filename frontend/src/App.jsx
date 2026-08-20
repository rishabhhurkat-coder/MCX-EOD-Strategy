import { useEffect } from 'react'

export default function App() {
  useEffect(() => {
    document.title = 'MCX EOD Strategy'

    fetch('/api/health')
      .then((response) => {
        if (!response.ok) throw new Error(`Bridge returned ${response.status}`)
        return response.json()
      })
      .then((health) => {
        window.__MCX_BRIDGE__ = health
      })
      .catch((error) => {
        window.__MCX_BRIDGE_ERROR__ = error.message
      })
  }, [])

  return null
}
