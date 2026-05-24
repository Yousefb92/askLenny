import { useState, useRef, useEffect, useLayoutEffect } from 'react'

const API = ''   // relative — proxied by Vite in dev, nginx in Docker

/* ──────────────────────────────────────────────────────────
   INDIVIDUAL MESSAGE BUBBLE
   ────────────────────────────────────────────────────────── */
function Message({ msg, dbName, onRerun, isRerunning }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(msg.sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (msg.role === 'user') {
    return (
      <div className="qe-msg qe-msg-user">
        <div className="qe-bubble-user">{msg.content}</div>
      </div>
    )
  }

  if (msg.isError) {
    return (
      <div className="qe-msg qe-msg-assistant">
        <div className="qe-bubble-error">
          <span className="qe-error-icon">⚠</span>
          {msg.content}
        </div>
      </div>
    )
  }

  // Assistant SQL message
  const isNoContext = msg.sql?.toLowerCase().startsWith('i do not have enough')

  if (isNoContext) {
    return (
      <div className="qe-msg qe-msg-assistant">
        <div className="qe-bubble-error" style={{ borderColor: 'rgba(245,158,11,0.35)', color: '#fcd34d', backgroundColor: 'rgba(245,158,11,0.08)' }}>
          <span className="qe-error-icon">ℹ</span>
          {msg.sql}
        </div>
      </div>
    )
  }

  return (
    <div className="qe-msg qe-msg-assistant">
      <div className="qe-sql-card">
        <div className="qe-sql-toolbar">
          <span className="qe-sql-label">Generated SQL · {dbName}</span>
          <div className="qe-sql-actions">
            <button className="qe-copy-btn" onClick={copy}>
              {copied ? '✓ Copied' : 'Copy'}
            </button>
            <button
              className={`qe-run-btn${isRerunning ? ' qe-run-btn-loading' : ''}`}
              onClick={() => onRerun(msg.sql, msg.id)}
              disabled={isRerunning}
              title="Re-run this query against the database"
            >
              {isRerunning ? '⏳ Running…' : '↺ Re-run'}
            </button>
          </div>
        </div>
        <pre className="qe-sql-code">{msg.sql}</pre>
        {msg.rowCount !== undefined && (
          <div className="qe-sql-result-chip">
            ✓ Returned {msg.rowCount} row{msg.rowCount !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}

/* ──────────────────────────────────────────────────────────
   THINKING INDICATOR
   ────────────────────────────────────────────────────────── */
function ThinkingBubble({ label }) {
  return (
    <div className="qe-msg qe-msg-assistant">
      <div className="qe-thinking">
        <span className="qe-dot" />
        <span className="qe-dot" />
        <span className="qe-dot" />
        {label && <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>}
      </div>
    </div>
  )
}

/* ──────────────────────────────────────────────────────────
   RESULTS PANE
   ────────────────────────────────────────────────────────── */
function ResultsPane({ results, isLoading }) {
  if (isLoading) {
    return (
      <div className="qe-results-pane">
        <div className="qe-results-placeholder">
          <div className="loading-spinner" style={{ width: 24, height: 24 }} />
          <p>Generating SQL and executing…</p>
        </div>
      </div>
    )
  }

  if (!results) {
    return (
      <div className="qe-results-pane">
        <div className="qe-results-placeholder">
          <span className="qe-results-placeholder-icon">⬛</span>
          <p>Results will appear here automatically after each query</p>
        </div>
      </div>
    )
  }

  if (results.error) {
    return (
      <div className="qe-results-pane">
        <div className="qe-results-header">
          <span className="qe-results-title qe-results-title-error">Execution Error</span>
        </div>
        <div className="qe-results-error-body">{results.error}</div>
      </div>
    )
  }

  const isEmpty = !results.rows || results.rows.length === 0

  return (
    <div className="qe-results-pane">
      <div className="qe-results-header">
        <span className="qe-results-title">
          {results.rowCount} row{results.rowCount !== 1 ? 's' : ''}
          <span className="qe-results-meta">
            {results.columns?.length > 0 && ` · ${results.columns.length} column${results.columns.length !== 1 ? 's' : ''}`}
          </span>
        </span>
        <span className="qe-results-time">{results.executedAt?.toLocaleTimeString()}</span>
      </div>

      {isEmpty ? (
        <div className="qe-results-placeholder" style={{ flex: 1 }}>
          <p style={{ color: 'var(--text-muted)' }}>Query executed successfully — no rows returned</p>
        </div>
      ) : (
        <div className="qe-table-scroll">
          <table className="qe-table">
            <thead>
              <tr>
                {results.columns.map(col => <th key={col}>{col}</th>)}
              </tr>
            </thead>
            <tbody>
              {results.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>
                      {cell === null
                        ? <span className="qe-null">NULL</span>
                        : String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ──────────────────────────────────────────────────────────
   MAIN QUERY ENGINE
   ────────────────────────────────────────────────────────── */
export default function QueryEngine({ schemaData }) {
  const dbNames = Object.keys(schemaData)

  const [selectedDb,   setSelectedDb]   = useState('')
  const [messages,     setMessages]     = useState([])
  const [input,        setInput]        = useState('')
  const [isAsking,     setIsAsking]     = useState(false)   // full pipeline running
  const [isRerunning,  setIsRerunning]  = useState(false)   // re-execute only
  const [rerunMsgId,   setRerunMsgId]   = useState(null)
  const [results,      setResults]      = useState(null)

  const chatEndRef = useRef(null)
  const inputRef   = useRef(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isAsking])

  useLayoutEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = `${inputRef.current.scrollHeight}px`
    }
  }, [input])

  const handleDbChange = (db) => {
    setSelectedDb(db)
    setMessages([])
    setResults(null)
  }

  // ── Full pipeline: embed → search → generate → execute ────
  const handleAsk = async () => {
    const question = input.trim()
    if (!question || !selectedDb || isAsking) return

    setInput('')
    setResults(null)
    setMessages(prev => [...prev, { id: Date.now(), role: 'user', content: question }])
    setIsAsking(true)

    try {
      const res = await fetch(`${API}/query/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, db_name: selectedDb, limit: 10 }),
      })

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail.detail || `Server error: HTTP ${res.status}`)
      }

      const json = await res.json()
      if (json.status !== 'success') throw new Error(json.detail || 'Unexpected response')

      // Show SQL in chat
      setMessages(prev => [...prev, {
        id:       Date.now() + 1,
        role:     'assistant',
        sql:      json.sql,
        content:  json.sql,
        rowCount: json.row_count,
      }])

      // Show results automatically
      setResults({
        columns:     json.columns,
        rows:        json.rows,
        rowCount:    json.row_count,
        executedAt:  new Date(),
      })

    } catch (err) {
      setMessages(prev => [...prev, {
        id:      Date.now() + 1,
        role:    'assistant',
        isError: true,
        content: err.message,
      }])
    } finally {
      setIsAsking(false)
    }
  }

  // ── Re-run a previous SQL (↺ Re-run button) ──────────────
  const handleRerun = async (sql, msgId) => {
    setIsRerunning(true)
    setRerunMsgId(msgId)
    setResults(null)

    try {
      const res = await fetch(`${API}/query/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql, db_name: selectedDb }),
      })

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail.detail || `Server error: HTTP ${res.status}`)
      }

      const json = await res.json()
      if (json.status !== 'success') throw new Error(json.detail || 'Execution failed')

      setResults({
        columns:    json.columns,
        rows:       json.rows,
        rowCount:   json.row_count,
        executedAt: new Date(),
      })
    } catch (err) {
      setResults({ error: err.message })
    } finally {
      setIsRerunning(false)
      setRerunMsgId(null)
    }
  }

  const canSend = !!selectedDb && !!input.trim() && !isAsking

  return (
    <div className="qe-shell">

      {/* ── Header ───────────────────────────────────────── */}
      <div className="qe-header">
        <div>
          <h1 className="page-title">Query Engine</h1>
          <p className="qe-subtitle">
            Ask in plain English — askLenny finds the schema context, generates the SQL, and runs it
          </p>
        </div>

        <div className="qe-db-selector">
          <label className="qe-db-label">Active database</label>
          <select
            className="qe-db-select"
            value={selectedDb}
            onChange={e => handleDbChange(e.target.value)}
          >
            <option value="">Select a database…</option>
            {dbNames.map(db => (
              <option key={db} value={db}>{db}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Workspace ────────────────────────────────────── */}
      <div className="qe-workspace">

        {/* Chat pane */}
        <div className="qe-chat-pane">
          <div className="qe-messages">

            {messages.length === 0 && !isAsking && (
              <div className="qe-empty">
                <div className="qe-empty-icon">
                  <svg viewBox="0 0 32 32" width={36} height={36} aria-hidden="true" style={{ opacity: 0.35 }}>
                    <defs>
                      <linearGradient id="qe-top" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%"   stopColor="#4a5fa8" />
                        <stop offset="100%" stopColor="#1e2a50" />
                      </linearGradient>
                    </defs>
                    <rect x="4" y="9" width="16" height="14" fill="#141c38" />
                    <ellipse cx="12" cy="23" rx="8" ry="3" fill="#0e1525" stroke="#253058" strokeWidth="0.7" />
                    <ellipse cx="12" cy="9"  rx="8" ry="3" fill="url(#qe-top)" stroke="#3d508a" strokeWidth="0.7" />
                    <path d="M20,12 Q27,11 31,7"  stroke="#1fff90" strokeWidth="1.1" fill="none" />
                    <path d="M20,16 Q28,16 31,16" stroke="#6677ff" strokeWidth="1.1" fill="none" />
                    <path d="M20,20 Q27,21 31,25" stroke="#ff3fa0" strokeWidth="1.1" fill="none" />
                  </svg>
                </div>
                <p className="qe-empty-title">
                  {selectedDb ? `Ready to query ${selectedDb}` : 'Select a database to get started'}
                </p>
                <p className="qe-empty-hint">
                  Try: "Show me all users who signed up in the last 30 days"
                </p>
              </div>
            )}

            {messages.map(msg => (
              <Message
                key={msg.id}
                msg={msg}
                dbName={selectedDb}
                onRerun={handleRerun}
                isRerunning={isRerunning && rerunMsgId === msg.id}
              />
            ))}

            {isAsking && <ThinkingBubble label="Searching schema · generating SQL · executing…" />}
            <div ref={chatEndRef} />
          </div>

          {/* Input */}
          <div className="qe-input-row">
            <textarea
              ref={inputRef}
              className="qe-input"
              placeholder={
                selectedDb
                  ? `Ask a question about ${selectedDb}… (Enter to send)`
                  : 'Select a database above first…'
              }
              value={input}
              rows={1}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleAsk()
                }
              }}
              disabled={!selectedDb || isAsking}
            />
            <button
              className="qe-send-btn"
              onClick={handleAsk}
              disabled={!canSend}
              title="Send (Enter)"
            >
              ↑
            </button>
          </div>
        </div>

        {/* Results pane — updates automatically on every ask */}
        <ResultsPane results={results} isLoading={isAsking || isRerunning} />
      </div>
    </div>
  )
}
