import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { getRouter } from './router'
import { AuthProvider } from './context/AuthContext'
import './styles.css'

// Global fetch wrapper to automatically inject ngrok-skip-browser-warning header
const originalFetch = window.fetch;
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  if (input instanceof Request) {
    input.headers.set('ngrok-skip-browser-warning', 'true');
  } else {
    init = init || {};
    const headers = init.headers || {};
    if (headers instanceof Headers) {
      headers.set('ngrok-skip-browser-warning', 'true');
    } else if (Array.isArray(headers)) {
      headers.push(['ngrok-skip-browser-warning', 'true']);
    } else {
      init.headers = {
        ...headers,
        'ngrok-skip-browser-warning': 'true'
      };
    }
  }
  return originalFetch(input, init);
};

const router = getRouter()

// Declare your instance for type safety
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </React.StrictMode>,
)
