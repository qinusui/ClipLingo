import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import './i18n'
import './index.css'

const App = lazy(() => import('./App'));
const PlayerMode = lazy(() => import('./PlayerMode'));
const Root = window.location.pathname.startsWith('/player') ? PlayerMode : App;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Suspense fallback={<div className="min-h-screen bg-gray-50 dark:bg-gray-900" />}>
      <Root />
    </Suspense>
  </React.StrictMode>,
)
