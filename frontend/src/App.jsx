import { useEffect, useRef, useState } from 'react'
import './App.css'
import { runSingleFlight } from './singleFlight.js'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const API_IS_LOCAL = (() => {
  try { return ['localhost', '127.0.0.1', '::1'].includes(new URL(API_URL).hostname) } catch { return false }
})()

function Icon({ name, size = 18 }) {
  const paths = {
    upload: <><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M20 16.5v2A1.5 1.5 0 0 1 18.5 20h-13A1.5 1.5 0 0 1 4 18.5v-2"/></>,
    file: <><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7M8 14h8M8 18h8"/></>,
    arrow: <><path d="M7 17 17 7M7 7h10v10"/></>,
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v3h16v-3"/></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></>,
    close: <><path d="m18 6-12 12M6 6l12 12"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function App() {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [checked, setChecked] = useState({})
  const [health, setHealth] = useState({ ready: false, checked: false, model: 'qwen3:4b' })
  const [inferenceStatus, setInferenceStatus] = useState('untested')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const requestInFlight = useRef(false)
  const requestStartedAt = useRef(0)

  useEffect(() => {
    if (status !== 'loading') return undefined
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - requestStartedAt.current) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [status])

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_URL}/api/health`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('Health check failed')))
      .then((data) => setHealth({ ready: !!data.model_available, ollamaReachable: !!data.ollama_reachable, checked: true, model: data.model || 'qwen3:4b', detail: data.detail || (data.model_available ? 'Ollama is reachable and this model is listed. Generation is verified only after analysis.' : 'The configured Ollama model is unavailable.') }))
      .catch((err) => { if (err.name !== 'AbortError') setHealth((old) => ({ ...old, ready: false, ollamaReachable: false, checked: true, detail: 'Local API or Ollama is unavailable.' })) })
    return () => controller.abort()
  }, [])

  const chooseFile = (nextFile) => {
    if (!nextFile || requestInFlight.current) return
    const ext = nextFile.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'txt'].includes(ext)) {
      setError('Choose a PDF or TXT file to continue.')
      return
    }
    setError('')
    setFile(nextFile)
    setText('')
    setAnalysis(null)
    setStatus('idle')
  }

  const analyze = () => runSingleFlight(requestInFlight, async () => {
    if (!file && !text.trim()) {
      setError('Upload a notice or paste its text before analyzing.')
      return
    }
    requestStartedAt.current = Date.now()
    setElapsedSeconds(0)
    setError('')
    setStatus('loading')
    setInferenceStatus('running')
    setAnalysis(null)
    try {
      const form = new FormData()
      if (file) form.append('file', file)
      else form.append('text', text.trim())
      const response = await fetch(`${API_URL}/api/analyze`, { method: 'POST', body: form })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || `Analysis failed (${response.status}).`)
      setAnalysis(payload)
      setStatus('ready')
      setInferenceStatus('succeeded')
    } catch (err) {
      setError(err instanceof TypeError ? `Could not reach NoticeLens at ${API_URL}. Start the local API and try again.` : err.message)
      setStatus('error')
      setInferenceStatus('failed')
    }
  })

  const reset = () => {
    setFile(null); setText(''); setAnalysis(null); setError(''); setStatus('idle'); setChecked({})
    if (inputRef.current) inputRef.current.value = ''
  }

  const deadlines = analysis?.deadlines || []
  const tasks = analysis?.checklist || analysis?.tasks || []
  const summary = analysis?.summary || ''
  const title = analysis?.title || file?.name || 'Untitled circular'
  const source = analysis?.source_text || text
  const missing = analysis?.missing_information || analysis?.ambiguities || []

  const exportChecklist = () => {
    const lines = tasks.map((task, i) => `- [${checked[i] ? 'x' : ' '}] ${typeof task === 'string' ? task : task.text || task.title || JSON.stringify(task)}`)
    const blob = new Blob([`NoticeLens checklist\n${title}\n\n${lines.join('\n') || 'No checklist items to export.'}\n`], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'noticelens-checklist.txt'; anchor.click(); URL.revokeObjectURL(url)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NoticeLens home"><span className="brand-mark">N</span><span>Notice<span className="brand-light">Lens</span></span></a>
        <div className="topbar-right"><span className="privacy"><Icon name="shield" size={15}/> {API_IS_LOCAL ? 'Processed locally by Ollama' : 'Sent to configured API'}</span><span className={`model-tag ${health.ready && inferenceStatus !== 'failed' ? 'model-ready' : 'model-offline'}`} title={health.detail || 'The model-list check is not a generation test.'}><i/> {health.model}{inferenceStatus === 'running' ? ' · Generating' : inferenceStatus === 'succeeded' ? ' · Responded' : inferenceStatus === 'failed' ? ' · Request failed' : health.checked ? health.ready ? ' · Listed' : health.ollamaReachable ? ' · Not listed' : ' · Offline' : ' · Checking'}</span></div>
      </header>

      <main id="top" className="workspace">
        <div className="page-heading">
          <div><p className="eyebrow">THE STUDENT’S NOTICE DESK <span>·</span> 01</p><h1>Make sense of<br className="mobile-break"/> the fine print.</h1><p className="intro">Turn university circulars into clear next steps. {API_IS_LOCAL ? 'Your document stays on your machine.' : 'Your document is sent to the configured API.'}</p></div>
          <div className="edition">A clearer read<br/><span>for campus life</span></div>
        </div>

        <section className="intake" aria-label="Add a university notice">
          <div className="intake-label"><span className="step-number">01</span><div><h2>Start with a notice</h2><p>Drop in a circular or paste the text below.</p></div></div>
          <div className={`dropzone ${dragging ? 'is-dragging' : ''}`} onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); chooseFile(e.dataTransfer.files[0]) }}>
            <input ref={inputRef} type="file" accept=".pdf,.txt,application/pdf,text/plain" onChange={(e) => chooseFile(e.target.files[0])} aria-label="Choose PDF or TXT notice" disabled={status === 'loading'} />
            <span className="upload-icon"><Icon name="upload" size={20}/></span>
            <div className="drop-copy">{file ? <><strong>{file.name}</strong><span>{(file.size / 1024).toFixed(0)} KB · Ready to read</span></> : <><strong>Drop a PDF or TXT here</strong><span>or <button className="text-button" type="button" onClick={() => inputRef.current?.click()}>browse files</button></span></>}</div>
            {file && <button className="icon-button" onClick={(e) => { e.stopPropagation(); reset() }} aria-label="Remove file" disabled={status === 'loading'}><Icon name="close" size={16}/></button>}
            <span className="file-kind">PDF / TXT</span>
          </div>
          <div className="paste-row"><span className="or-label">OR PASTE TEXT</span><textarea value={text} onChange={(e) => { setText(e.target.value); setFile(null); setAnalysis(null) }} placeholder="Paste the full circular here…" rows="2" aria-label="Paste notice text" disabled={status === 'loading'}/><button className="analyze-button" type="button" onClick={analyze} disabled={status === 'loading'}>{status === 'loading' ? <><span className="spinner"/> Generating locally</> : <>Read this notice <Icon name="arrow" size={16}/></>}</button></div>
          {error && <p className="error-message" role="alert">{error}</p>}
        </section>

        {status === 'loading' && <div className="loading-line" role="status"><span className="spinner"/><div className="loading-copy"><span>{elapsedSeconds < 15 ? 'The local model is reading your notice…' : `Qwen is still generating (${elapsedSeconds}s).`}</span><small>First use can take longer while Ollama loads the model. The interface waits for a complete, verified response.</small></div></div>}
        {status === 'idle' && !analysis && <div className="empty-note"><span className="empty-rule"/><p>Your reading notes will appear here once you add a circular.</p><span className="empty-rule"/></div>}

        {analysis && <section className="results" aria-live="polite">
          <div className="result-heading"><div><p className="eyebrow">YOUR READING NOTES <span>·</span> 02</p><h2>{title}</h2></div><button className="quiet-button" onClick={reset}>Start over</button></div>
          <div className="overview-grid">
            <article className="summary-block"><p className="section-kicker">IN BRIEF</p><p className="summary-text">{summary || 'No summary was returned for this notice.'}</p>{analysis.summary_evidence && <details className="evidence summary-evidence"><summary>Basis in notice</summary><blockquote>{analysis.summary_evidence}</blockquote></details>}<div className="audience"><span>WHO IT AFFECTS</span><strong>{analysis.audience || analysis.who_it_affects || 'Not specified in the notice'}</strong></div>{analysis.audience_evidence && <details className="evidence audience-evidence"><summary>Source</summary><blockquote>{analysis.audience_evidence}</blockquote></details>}</article>
            <aside className="uncertainty"><p className="section-kicker">NEEDS A SECOND LOOK</p>{missing.length ? <ul>{missing.map((item, i) => <li key={i}>{typeof item === 'string' ? item : item.text || item.description}</li>)}</ul> : <p>No ambiguities were returned. Check the source before acting on important dates.</p>}</aside>
          </div>
          <div className="content-grid">
            <section className="deadline-section"><div className="section-header"><div><p className="section-kicker">DATES TO KEEP</p><h3>Deadlines</h3></div><span className="sort-note">Soonest first</span></div>
              {deadlines.length ? <ol className="deadline-list">{[...deadlines].sort((a,b) => new Date(a.date || a.deadline || '9999') - new Date(b.date || b.deadline || '9999')).map((item,i) => <li key={i}><div className="date-stamp"><strong>{item.day || (item.date || item.deadline || '—').slice(8,10)}</strong><span>{item.month || (item.date || item.deadline || '').slice(5,7)}</span></div><div className="deadline-detail"><strong>{item.title || item.label || item.description || item.date}</strong><span>{item.date || item.deadline || 'Date unclear'}{item.time ? ` · ${item.time}` : ''}</span>{(item.evidence || item.source_excerpt || item.excerpt) && <details className="evidence"><summary>See source</summary><blockquote>{item.evidence || item.source_excerpt || item.excerpt}</blockquote></details>}</div><span className="urgency">{item.urgency || item.status || 'DATE'}</span></li>)}</ol> : <p className="section-empty">No deadlines were identified in the analysis.</p>}
            </section>
            <section className="checklist-section"><div className="section-header"><div><p className="section-kicker">MAKE IT HAPPEN</p><h3>Your checklist</h3></div><button className="export-button" onClick={exportChecklist}><Icon name="download" size={15}/> Export</button></div>
              {tasks.length ? <ul className="task-list">{tasks.map((task,i) => { const label = typeof task === 'string' ? task : task.text || task.title || task.action || 'Checklist item'; return <li key={i}><label className={checked[i] ? 'task-done' : ''}><input type="checkbox" checked={!!checked[i]} onChange={() => setChecked((old) => ({...old, [i]: !old[i]}))}/><span className="custom-check"><Icon name="check" size={13}/></span><span>{label}</span></label>{typeof task === 'object' && (task.evidence || task.source_excerpt || task.excerpt) && <details className="evidence task-evidence"><summary>Source</summary><blockquote>{task.evidence || task.source_excerpt || task.excerpt}</blockquote></details>}</li>})}</ul> : <p className="section-empty">No action items were returned.</p>}
            </section>
          </div>
          {source && <details className="source-panel"><summary><Icon name="file" size={16}/> View notice text</summary><pre>{source}</pre></details>}
        </section>}
      </main>
      <footer className="footer"><span>NoticeLens <span className="footer-sep">/</span> Read carefully. Act confidently.</span><span><Icon name="shield" size={14}/> {API_IS_LOCAL ? 'Local inference' : 'Configured API'} {inferenceStatus === 'running' ? 'in progress' : inferenceStatus === 'succeeded' ? 'last run succeeded' : inferenceStatus === 'failed' ? 'last run failed' : health.checked ? health.ready ? 'model listed; not yet tested' : 'unavailable' : 'status checking'}</span></footer>
    </div>
  )
}

export default App
