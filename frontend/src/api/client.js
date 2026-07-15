import axios from 'axios'

export const API_BASE =
  import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const client = axios.create({
  baseURL: API_BASE,
})

// Attach JWT on every request.
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle 401 (clear + redirect) and 451 (geofence full-page block).
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      localStorage.removeItem('token')
      if (window.location.pathname !== '/') {
        window.location.href = '/'
      }
    } else if (status === 451) {
      window.dispatchEvent(new CustomEvent('geo-blocked'))
    }
    return Promise.reject(error)
  }
)

export default client
