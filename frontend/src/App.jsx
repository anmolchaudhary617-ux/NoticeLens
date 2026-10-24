import { useEffect, useRef, useState } from 'react'
import './App.css'
import { runSingleFlight } from './singleFlight.js'
import { formatDeadlineDay, formatDeadlineLabel } from './deadlineFormatting.js'

const API_URL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '')
const BACKEND_UNAVAILABLE_MESSAGE = 'AI analysis requires the local backend and is not available to other visitors.'
const API_IS_LOCAL = (() => {
  if (!API_URL) return false
  try {
    return ['localhost', '127.0.0.1', '::1', '[::1]'].includes(new URL(API_URL).hostname)
  } catch {
    return false
  }
})()

function Icon({ name, size = 18 }) {
  const paths = {
    arrow: <><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    close: <><path d="m18 6-12 12M6 6l12 12"/></>,
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v3h16v-3"/></>,
    file: <><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7M8 14h8M8 18h8"/></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></>,
    upload: <><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M20 16.5v2A1.5 1.5 0 0 1 18.5 20h-13A1.5 1.5 0 0 1 4 18.5v-2"/></>,
  }

  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function ModelStatus({ health, inferenceStatus }) {
  let label = API_URL ? 'Checking API' : 'Local backend required'
  if (inferenceStatus === 'running') label = 'Analysis running'
  else if (inferenceStatus === 'succeeded') label = 'Last run responded'
  else if (inferenceStatus === 'failed') label = 'Last request failed'
  else if (health.checked && health.ready) label = 'Model listed'
  else if (health.checked && health.ollamaReachable) label = 'Model not found'
  else if (health.checked) label = 'API offline'

  const tone = inferenceStatus === 'failed'
    ? 'is-error'
    : inferenceStatus === 'succeeded' || (inferenceStatus === 'untested' && health.ready)
      ? 'is-available'
      : inferenceStatus === 'running' ? 'is-running' : 'is-unavailable'

  return (
    <div className={`model-status ${tone}`} title={health.detail || 'A model-list check does not verify that inference will succeed.'}>
      <span className="status-dot" aria-hidden="true" />
      <span className="model-status-copy"><strong>{health.model || 'qwen3:4b'}</strong><span>{label}</span></span>
    </div>
  )
}

function Evidence({ quote, sourceRef, label = 'View evidence' }) {
  if (!quote) return null
  return (
    <details className="evidence">
      <summary>{label}</summary>
      <blockquote>{quote}</blockquote>
      <a className="source-jump" href="#source-document" onClick={() => { if (sourceRef.current) sourceRef.current.open = true }}>
        Open original notice text
      </a>
    </details>
  )
}

function DeadlineRow({ item, sourceRef }) {
  const isoDate = typeof item.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(item.date) ? item.date : ''
  const day = formatDeadlineDay(item)
  const month = item.month || (isoDate ? new Date(`${isoDate}T12:00:00`).toLocaleString('en', { month: 'short' }) : '')
  const year = isoDate ? isoDate.slice(0, 4) : ''
  const dateLabel = formatDeadlineLabel(item)
  const title = item.title || item.label || item.description || 'Deadline'

  return (
    <li className="deadline-row">
      {isoDate ? (
        <time className="deadline-date" dateTime={isoDate}>
          <span className="deadline-day">{day}</span>
          <span className="deadline-month">{month} {year}</span>
        </time>
      ) : (
        <span className="deadline-date is-unconfirmed"><Icon name="file" size={19}/><span>Confirm<br/>date</span></span>
      )}
      <div className="deadline-content">
        <h4>{title}</h4>
        <p className="deadline-full-date">{dateLabel}</p>
        {item.ambiguity && <p className="deadline-note">{item.ambiguity}</p>}
        <Evidence quote={item.evidence || item.source_excerpt || item.excerpt} sourceRef={sourceRef} label="View supporting text" />
      </div>
    </li>
  )
}

function ChecklistRow({ task, index, checked, onToggle, sourceRef }) {
  const label = typeof task === 'string' ? task : task.text || task.title || task.action || 'Checklist item'
  const evidence = typeof task === 'object' ? task.evidence || task.source_excerpt || task.excerpt : ''
  return (
    <li className={`task-row ${checked ? 'is-complete' : ''}`}>
      <label className="task-label">
        <input type="checkbox" checked={checked} onChange={() => onToggle(index)} />
        <span className="task-check" aria-hidden="true"><Icon name="check" size={15}/></span>
        <span className="task-text">{label}</span>
      </label>
      <Evidence quote={evidence} sourceRef={sourceRef} label="View source" />
    </li>
  )
}

function App() {
  const inputRef = useRef(null)
  const sourceRef = useRef(null)
  const requestInFlight = useRef(false)
  const requestStartedAt = useRef(0)
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [checked, setChecked] = useState({})
  const [health, setHealth] = useState({
    ready: false,
    checked: !API_URL,
    model: 'qwen3:4b',
    detail: API_URL ? undefined : BACKEND_UNAVAILABLE_MESSAGE,
  })
  const [inferenceStatus, setInferenceStatus] = useState('untested')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  useEffect(() => {
    if (status !== 'loading') return undefined
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - requestStartedAt.current) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [status])

  useEffect(() => {
    if (!API_URL) return undefined
    const controller = new AbortController()
    fetch(`${API_URL}/api/health`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('Health check failed')))
      .then((data) => setHealth({
        ready: !!data.model_available,
        ollamaReachable: !!data.ollama_reachable,
        checked: true,
        model: data.model || 'qwen3:4b',
        detail: data.detail || 'The model-list check does not verify that inference will succeed.',
      }))
      .catch((err) => {
        if (err.name !== 'AbortError') setHealth((old) => ({ ...old, ready: false, ollamaReachable: false, checked: true, detail: 'The NoticeLens API or local Ollama service could not be reached.' }))
      })
    return () => controller.abort()
  }, [])

  const chooseFile = (nextFile) => {
    if (!nextFile || requestInFlight.current) return
    const extension = nextFile.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'txt'].includes(extension)) {
      setError('That file type is not supported. Choose a PDF or TXT notice.')
      if (inputRef.current) inputRef.current.value = ''
      return
    }
    setError('')
    setFile(nextFile)
    setText('')
    setAnalysis(null)
    setChecked({})
    setStatus('idle')
  }

  const handleTextChange = (event) => {
    setText(event.target.value)
    setFile(null)
    setAnalysis(null)
    setChecked({})
    setError('')
    setStatus('idle')
    if (inputRef.current) inputRef.current.value = ''
  }

  const analyze = () => runSingleFlight(requestInFlight, async () => {
    if (!API_URL) {
      setError(BACKEND_UNAVAILABLE_MESSAGE)
      return
    }
    if (!file && !text.trim()) {
      setError('Add a PDF, TXT file, or pasted notice before analyzing.')
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
      setError(err instanceof TypeError
        ? `Could not reach the NoticeLens API at ${API_URL}. Start or check the local API and try again.`
        : err.message || 'The analysis failed. Check the API and try again.')
      setStatus('error')
      setInferenceStatus('failed')
    }
  })

  const reset = () => {
    setFile(null)
    setText('')
    setAnalysis(null)
    setError('')
    setStatus('idle')
    setChecked({})
    if (inputRef.current) inputRef.current.value = ''
  }

  const deadlines = analysis?.deadlines || []
  const tasks = analysis?.checklist || analysis?.tasks || []
  const summary = analysis?.summary || ''
  const title = analysis?.title || file?.name || 'Untitled notice'
  const source = analysis?.source_text || text
  const missing = analysis?.missing_information || analysis?.ambiguities || []
  const completedCount = tasks.reduce((count, _, index) => count + (checked[index] ? 1 : 0), 0)

  const exportChecklist = () => {
    const lines = tasks.map((task, index) => {
      const label = typeof task === 'string' ? task : task.text || task.title || JSON.stringify(task)
      return `- [${checked[index] ? 'x' : ' '}] ${label}`
    })
    const blob = new Blob([`NoticeLens checklist\n${title}\n\n${lines.join('\n')}\n`], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'noticelens-checklist.txt'
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    chooseFile(event.dataTransfer.files[0])
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NoticeLens home">
          <span className="brand-mark">N</span>
          <span>Notice<span className="brand-light">Lens</span></span>
        </a>
        <div className="topbar-right">
          <span className="privacy-indicator" title={!API_URL ? BACKEND_UNAVAILABLE_MESSAGE : API_IS_LOCAL ? 'Notice text is sent to your loopback API and local Ollama instance.' : 'Notice text is sent to the API URL configured for this app.'}>
            <Icon name="shield" size={17}/>
            <span>{!API_URL ? 'Analysis unavailable' : API_IS_LOCAL ? 'Local processing' : 'Configured API'}</span>
          </span>
          <ModelStatus health={health} inferenceStatus={inferenceStatus}/>
        </div>
      </header>

      <main id="top" className="workspace">
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-copy">
            <p className="eyebrow">NOTICE ANALYSIS WORKSPACE</p>
            <h1 id="page-title">Know what matters.</h1>
            <p className="hero-description">Turn university notices into clear actions, deadlines, and evidence-backed summaries.</p>
          </div>
          <p className="hero-note"><Icon name="shield" size={18}/><span>{!API_URL ? BACKEND_UNAVAILABLE_MESSAGE : API_IS_LOCAL ? 'Your notice is processed on this device.' : 'Your notice is sent to the configured API.'}</span></p>
        </section>

        <section className="input-workspace" aria-label="Add a notice">
          <div className="workspace-heading">
            <div><span className="step-label">01</span><div><h2>Add a notice</h2><p>Upload a circular or paste its text to get started.</p></div></div>
            {file && <button className="text-action clear-action" type="button" onClick={reset} disabled={status === 'loading'}><Icon name="close" size={16}/> Clear notice</button>}
          </div>

          <div className="input-grid">
            <section className={`input-panel upload-panel ${dragging ? 'is-dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false) }} onDrop={handleDrop} aria-labelledby="upload-heading">
              <div className="panel-heading"><div><h3 id="upload-heading">Upload a file</h3><p>PDF or TXT · up to 10 MB</p></div><span className="panel-icon"><Icon name="file" size={19}/></span></div>
              <input ref={inputRef} className="visually-hidden" type="file" accept=".pdf,.txt,application/pdf,text/plain" onChange={(event) => chooseFile(event.target.files?.[0])} aria-label="Choose a PDF or TXT notice" disabled={status === 'loading'}/>
              {file ? (
                <div className="selected-file">
                  <span className="selected-file-icon"><Icon name="file" size={21}/></span>
                  <span className="selected-file-copy"><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(0)} KB · Ready to analyze</small></span>
                  <button className="icon-action" type="button" aria-label="Remove selected file" onClick={() => { setFile(null); setAnalysis(null); setChecked({}); setStatus('idle'); if (inputRef.current) inputRef.current.value = '' }} disabled={status === 'loading'}><Icon name="close" size={17}/></button>
                </div>
              ) : (
                <div className="dropzone-content">
                  <span className="upload-symbol"><Icon name="upload" size={22}/></span>
                  <p><strong>Drag and drop your notice</strong><span>or choose it from your device</span></p>
                  <button className="browse-button" type="button" onClick={() => inputRef.current?.click()} disabled={status === 'loading'}>Browse files</button>
                </div>
              )}
              <p className="file-note">Text-based PDFs work best. Scanned PDFs are not supported yet.</p>
            </section>

            <section className="input-panel paste-panel" aria-labelledby="paste-heading">
              <div className="panel-heading"><div><h3 id="paste-heading">Paste notice text</h3><p>Use copied text from an email or circular.</p></div><span className="panel-icon"><span className="text-icon">T</span></span></div>
              <label className="visually-hidden" htmlFor="notice-text">Paste notice text</label>
              <textarea id="notice-text" value={text} onChange={handleTextChange} placeholder="Paste the full notice here…" rows="7" disabled={status === 'loading'} aria-describedby="paste-hint"/>
              <div className="paste-meta"><span id="paste-hint">Keep the original wording for accurate evidence.</span><span>{text.length.toLocaleString()} characters</span></div>
            </section>
          </div>

          <div className="input-actions">
            <p><Icon name="shield" size={16}/><span>{!API_URL ? BACKEND_UNAVAILABLE_MESSAGE : API_IS_LOCAL ? 'Processed locally with Ollama' : 'Sent to the configured API'}</span></p>
            <button className="primary-button" type="button" onClick={analyze} disabled={status === 'loading' || !API_URL}>
              {status === 'loading' ? <><span className="spinner"/> Analyzing notice</> : <>Analyze notice <Icon name="arrow" size={17}/></>}
            </button>
          </div>
          {error && <div className="error-message" role="alert"><span className="error-symbol">!</span><p>{error}</p></div>}
        </section>

        {status === 'loading' && (
          <section className="loading-panel" role="status" aria-live="polite">
            <span className="loading-spinner"/>
            <div><h2>{elapsedSeconds < 15 ? 'Reading your notice' : `Still analyzing · ${elapsedSeconds}s`}</h2><p>The local model is preparing a complete response. First use may take longer while Ollama loads.</p></div>
            <span className="elapsed-time">{elapsedSeconds}s</span>
          </section>
        )}

        {status === 'idle' && !analysis && (
          <section className="empty-state" aria-label="What NoticeLens can find">
            <p className="empty-state-title">Your reading notes will appear here</p>
            <ul><li><span className="feature-dot"/> Key dates and deadlines</li><li><span className="feature-dot"/> Actions you can check off</li><li><span className="feature-dot"/> Source evidence and open questions</li></ul>
          </section>
        )}

        {analysis && (
          <section className="results" aria-live="polite">
            <div className="results-heading">
              <div><p className="eyebrow">ANALYSIS RESULTS</p><h2>{title}</h2></div>
              <button className="secondary-button" type="button" onClick={reset}>Analyze another notice</button>
            </div>

            <div className={`overview-grid ${missing.length ? 'has-uncertainty' : ''}`}>
              <section className="summary-panel" aria-labelledby="summary-heading">
                <div className="section-title-row"><div><p className="section-label">OVERVIEW</p><h3 id="summary-heading">In brief</h3></div><span className="generated-label">AI summary · source checked</span></div>
                {Array.isArray(analysis.summary_claims) && analysis.summary_claims.length ? (
                  <ul className="summary-claims">{analysis.summary_claims.map((claim, index) => <li key={index}><p className="summary-text">{claim.text}</p><Evidence quote={claim.evidence} sourceRef={sourceRef} label="Read supporting excerpt"/></li>)}</ul>
                ) : <><p className="summary-text">{summary || 'The model did not return a summary. Review the original notice below.'}</p><Evidence quote={analysis.summary_evidence} sourceRef={sourceRef} label="Read supporting excerpt"/></>}
                <div className="audience-row"><span className="audience-label">AFFECTED AUDIENCE</span><strong>{analysis.audience || analysis.who_it_affects || 'Not specified in the notice'}</strong></div>
                <Evidence quote={analysis.audience_evidence} sourceRef={sourceRef} label="Read audience evidence"/>
              </section>

              {missing.length > 0 && (
                <aside className="uncertainty-panel" aria-labelledby="uncertainty-heading">
                  <div className="uncertainty-heading"><span className="uncertainty-mark" aria-hidden="true">?</span><div><h3 id="uncertainty-heading">Needs a second look</h3><p>Check these details in the original notice.</p></div></div>
                  <ul>{missing.map((item, index) => <li key={index}>{typeof item === 'string' ? item : <>{item.text || item.description}<Evidence quote={item.evidence} sourceRef={sourceRef} label="Review related wording"/></>}</li>)}</ul>
                </aside>
              )}
            </div>

            <div className="results-grid">
              <section className="result-panel deadlines-panel" aria-labelledby="deadlines-heading">
                <div className="section-title-row">
                  <div><p className="section-label">DATES &amp; DEADLINES</p><h3 id="deadlines-heading">Key dates <span className="count-badge">{deadlines.length}</span></h3></div>
                  {deadlines.length > 1 && <span className="sort-label">Confirmed dates first</span>}
                </div>
                {deadlines.length ? (
                  <ol className="deadline-list">{[...deadlines].map((item, originalIndex) => ({ item, originalIndex })).sort((a, b) => { const dateA = /^\d{4}-\d{2}-\d{2}$/.test(a.item.date || '') ? a.item.date : '9999-99-99'; const dateB = /^\d{4}-\d{2}-\d{2}$/.test(b.item.date || '') ? b.item.date : '9999-99-99'; return dateA.localeCompare(dateB) || a.originalIndex - b.originalIndex }).map(({ item }, index) => <DeadlineRow key={`${item.date || item.deadline || 'date'}-${index}`} item={item} sourceRef={sourceRef}/>)}</ol>
                ) : <div className="section-empty"><span className="empty-icon"><Icon name="file" size={19}/></span><p>No deadlines were identified in this analysis.</p></div>}
              </section>

              <section className="result-panel checklist-panel" aria-labelledby="checklist-heading">
                <div className="section-title-row">
                  <div><p className="section-label">NEXT STEPS</p><h3 id="checklist-heading">Your checklist <span className="count-badge">{tasks.length}</span></h3></div>
                  <button className="export-button" type="button" onClick={exportChecklist} disabled={!tasks.length}><Icon name="download" size={17}/> Export</button>
                </div>
                {tasks.length ? (
                  <>
                    <p className="completion-label">{completedCount} of {tasks.length} complete</p>
                    <ul className="task-list">{tasks.map((task, index) => <ChecklistRow key={index} task={task} index={index} checked={!!checked[index]} onToggle={(taskIndex) => setChecked((old) => ({ ...old, [taskIndex]: !old[taskIndex] }))} sourceRef={sourceRef}/>)}</ul>
                  </>
                ) : <div className="section-empty"><span className="empty-icon"><Icon name="check" size={19}/></span><p>No checklist actions were returned.</p></div>}
              </section>
            </div>

            {source && (
              <details id="source-document" className="source-document" ref={sourceRef}>
                <summary><span className="source-summary-icon"><Icon name="file" size={18}/></span><span><strong>Original notice</strong><small>Review the text used for this analysis</small></span><span className="source-open-label">View source text</span></summary>
                <pre>{source}</pre>
              </details>
            )}
          </section>
        )}
      </main>

      <footer className="footer"><span>NoticeLens <span className="footer-separator">·</span> Read carefully. Act confidently.</span><span><Icon name="shield" size={15}/>{!API_URL ? 'Local backend required for analysis' : API_IS_LOCAL ? 'Local-first analysis' : 'Configured API processing'}</span></footer>
    </div>
  )
}

export default App
