import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import PlayerMode from './PlayerMode'
import './i18n'
import './index.css'

const Root = window.location.pathname.startsWith('/player') ? PlayerMode : App;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
