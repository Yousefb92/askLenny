import React, { useState, useEffect, useLayoutEffect, useMemo, useCallback } from 'react';
import './App.css';
import { useSchemaData } from './hooks/useSchemaData';
import { DatabasePane, TablePane, FieldPane } from './components/DiscoveryPanes';
import TopNav from './components/TopNav'
import QueryEngine from './components/QueryEngine';

/* ──────────────────────────────────────────────────────────
   TOAST NOTIFICATION
   ────────────────────────────────────────────────────────── */
function Toast({ toast }) {
  if (!toast) return null;
  const isSuccess = toast.type === 'success';
  return (
    <div className="toast-wrap">
      <div className={`toast toast-${toast.type}`}>
        <span className="toast-icon">{isSuccess ? '✓' : '⚠'}</span>
        <div>
          <div className="toast-title">{isSuccess ? 'Success' : 'Error'}</div>
          <div className="toast-body">{toast.message}</div>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
   APP
   ────────────────────────────────────────────────────────── */
function App() {
  const {
    schemaData, isLoading, error,
    isGeneratingFor, handleDescriptionChange, handleAutoEnrich,
    handleAutoEnrichTable, handleFkChange, resetAfterCommit,
  } = useSchemaData();

  // Navigation
  const [activeTab,     setActiveTab]     = useState('discovery');
  const [selectedDb,    setSelectedDb]    = useState(null);
  const [selectedTable, setSelectedTable] = useState(null);
  const [selectedColumn, setSelectedColumn] = useState(null);

  // Commit state
  const [isCommitting, setIsCommitting] = useState(false);
  const [toast, setToast] = useState(null);

  // Auto-resize textareas on every render (fallback for browsers without field-sizing).
  // useLayoutEffect runs synchronously after DOM mutations so scrollHeight is accurate.
  useLayoutEffect(() => {
    document.querySelectorAll('.enrich-input').forEach(ta => {
      ta.style.height = 'auto';
      ta.style.height = `${ta.scrollHeight}px`;
    });
  });

  // ── Navigation handlers ───────────────────────────────────
  const handleDbClick = useCallback((dbName) => {
    setSelectedDb(dbName);
    setSelectedTable(null);
    setSelectedColumn(null);
  }, []);

  const handleTableClick = useCallback((tableName) => {
    setSelectedTable(tableName);
    setSelectedColumn(null);
  }, []);

  // ── AI enrich (wraps hook fn so errors surface as toasts) ──
  const handleEnrich = useCallback(async (...args) => {
    try {
      await handleAutoEnrich(...args);
    } catch {
      showToast('error', 'Could not reach the AI engine. Check the app container is running.');
    }
  }, [handleAutoEnrich]);

  const handleEnrichTable = useCallback(async (...args) => {
    try {
      await handleAutoEnrichTable(...args);
    } catch {
      showToast('error', 'Could not reach the AI engine. Check the app container is running.');
    }
  }, [handleAutoEnrichTable]);

  // ── Toast helper ──────────────────────────────────────────
  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4500);
  };

  // ── Pending count for commit button badge ─────────────────
  const pendingCount = useMemo(() => {
    let n = 0;
    Object.values(schemaData).forEach(db => {
      if (db.status === 'Modified') n++;
      Object.values(db.tables || {}).forEach(tbl => {
        if (tbl.status === 'Modified') n++;
        Object.values(tbl.columns || {}).forEach(col => {
          if (col.status === 'Modified') n++;
        });
      });
    });
    return n;
  }, [schemaData]);

  // ── Commit to graph ───────────────────────────────────────
  const handleCommit = async () => {
    setIsCommitting(true);
    try {
      const response = await fetch('/sync/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(schemaData),
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const json = await response.json();

      if (json.status === 'success') {
        resetAfterCommit(); // flip Modified → Synchronized in local state
        showToast('success', json.message || 'Schema committed to the graph.');
      } else {
        showToast('error', json.message || 'Commit returned an unexpected status.');
      }
    } catch (err) {
      console.error('Commit failed:', err);
      showToast('error', 'Could not reach the Python backend. Is the app container running?');
    } finally {
      setIsCommitting(false);
    }
  };

  // ── Breadcrumb ────────────────────────────────────────────
  const breadcrumb = useMemo(() => {
    const parts = [];
    if (selectedDb)    parts.push(selectedDb);
    if (selectedTable) parts.push(selectedTable);
    return parts;
  }, [selectedDb, selectedTable]);

  // ── Loading / error states ────────────────────────────────
  if (isLoading) {
    return (
      <div className="fullscreen-state">
        <div className="loading-spinner" />
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Connecting to orchestrator…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fullscreen-state">
        <p style={{ color: '#f87171', fontSize: 18, fontWeight: 600 }}>Connection failed</p>
        <p style={{ color: 'var(--text-muted)', fontSize: 13, maxWidth: 400, textAlign: 'center', lineHeight: 1.6 }}>
          {error}
        </p>
        <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          Make sure the Python app container is running on port 8000.
        </p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <TopNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
        pendingCount={pendingCount}
        onCommit={handleCommit}
        isCommitting={isCommitting}
      />

      <Toast toast={toast} />

      {activeTab === 'discovery' && (
        <div className="page-content">
          {/* Header */}
          <div className="page-header">
            <h1 className="page-title">Schema Discovery</h1>
            <div className="page-breadcrumb">
              {breadcrumb.length === 0 ? (
                <span>Select a database to begin enrichment</span>
              ) : (
                breadcrumb.map((part, i) => (
                  <React.Fragment key={part}>
                    {i > 0 && <span className="breadcrumb-sep">›</span>}
                    <span className="breadcrumb-item">{part}</span>
                  </React.Fragment>
                ))
              )}
            </div>
          </div>

          {/* Three-pane workspace */}
          <div className="workspace">
            <DatabasePane
              schemaData={schemaData}
              selectedDb={selectedDb}
              onDbClick={handleDbClick}
              onDescriptionChange={handleDescriptionChange}
            />

            {selectedDb && schemaData[selectedDb] ? (
              <TablePane
                dbName={selectedDb}
                tablesData={schemaData[selectedDb].tables}
                selectedTable={selectedTable}
                onTableClick={handleTableClick}
                onDescriptionChange={handleDescriptionChange}
                onAutoEnrich={handleEnrich}
                isGeneratingFor={isGeneratingFor}
                parentDbDescription={schemaData[selectedDb]?.description}
              />
            ) : (
              <div className="pane pane-mid">
                <div className="pane-placeholder">
                  <span className="pane-placeholder-icon">⬅</span>
                  Select a database to see its tables
                </div>
              </div>
            )}

            {selectedDb && selectedTable && schemaData[selectedDb]?.tables[selectedTable] ? (
              <FieldPane
                dbName={selectedDb}
                tableName={selectedTable}
                columnsData={schemaData[selectedDb].tables[selectedTable].columns}
                selectedColumn={selectedColumn}
                onColumnClick={setSelectedColumn}
                onDescriptionChange={handleDescriptionChange}
                onAutoEnrich={handleEnrich}
                onAutoEnrichTable={handleEnrichTable}
                onFkChange={handleFkChange}
                isGeneratingFor={isGeneratingFor}
                parentTableDescription={schemaData[selectedDb]?.tables[selectedTable]?.description}
                schemaData={schemaData}
              />
            ) : (
              <div className="pane pane-wide">
                <div className="pane-placeholder">
                  <span className="pane-placeholder-icon">⬅</span>
                  Select a table to see its columns
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'graph' && (
        <div className="fullscreen-state">
          <p style={{ color: 'var(--text-muted)', fontSize: 15 }}>Graph Visualiser — coming soon</p>
        </div>
      )}

      {activeTab === 'query' && (
        <QueryEngine schemaData={schemaData} />
      )}
    </div>
  );
}

export default App;
