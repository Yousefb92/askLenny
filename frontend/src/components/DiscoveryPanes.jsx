import React from 'react';

/* ──────────────────────────────────────────────────────────
   STATUS HELPERS
   ────────────────────────────────────────────────────────── */

/**
 * Derive the four-state display status from an item's stored status + description.
 * Bug fix: replaces the fragile useRef-based `isModified` flag in every card.
 */
function getDisplayStatus(item) {
  if (!item) return 'New';
  if (item.status === 'Synchronized') return 'Synchronized';
  if (item.status === 'Modified') return 'Modified';
  // status === 'New': show Commit Pending once a description has been entered
  return item.description?.trim() ? 'Commit Pending' : 'New';
}

const STATUS_META = {
  'New':            { label: 'New',            badgeCls: 'badge-new',      cardCls: 'card-new' },
  'Synchronized':   { label: 'Synchronized',   badgeCls: 'badge-synced',   cardCls: 'card-synced' },
  'Modified':       { label: 'Modified',       badgeCls: 'badge-modified', cardCls: 'card-modified' },
  'Commit Pending': { label: 'Commit Pending', badgeCls: 'badge-pending',  cardCls: 'card-pending' },
};

const handleTextareaResize = (e) => {
  e.target.style.height = 'auto';
  e.target.style.height = `${e.target.scrollHeight}px`;
};

/**
 * Split a table dict key into its schema and short display name.
 *   "Orders"                    → { schema: 'dbo',   shortName: 'Orders' }
 *   "Sales.SalesOrderHeader"    → { schema: 'Sales', shortName: 'SalesOrderHeader' }
 */
function parseTableLabel(label) {
  const dot = label.indexOf('.');
  if (dot === -1) return { schema: 'dbo', shortName: label };
  return { schema: label.slice(0, dot), shortName: label.slice(dot + 1) };
}

/* ──────────────────────────────────────────────────────────
   PANE HEADER STATUS SUMMARY
   ────────────────────────────────────────────────────────── */
function PaneStatusSummary({ items }) {
  const counts = {};
  Object.values(items).forEach(item => {
    const s = getDisplayStatus(item);
    counts[s] = (counts[s] || 0) + 1;
  });

  const ORDER = ['New', 'Commit Pending', 'Modified', 'Synchronized'];

  return (
    <div className="pane-status-row">
      {ORDER.filter(s => counts[s]).map(s => (
        <span key={s} className={`badge ${STATUS_META[s].badgeCls}`}>
          {counts[s]} {STATUS_META[s].label}
        </span>
      ))}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
   CARD COMPONENTS
   ────────────────────────────────────────────────────────── */

const DatabaseCard = ({ dbName, dbData, selectedDb, onDbClick, onDescriptionChange }) => {
  const displayStatus = getDisplayStatus(dbData);
  const { label, badgeCls, cardCls } = STATUS_META[displayStatus];

  return (
    <div
      className={`card ${cardCls}${selectedDb === dbName ? ' active' : ''}`}
      onClick={() => onDbClick(dbName)}
    >
      <div className="card-header">
        <div className="card-meta">
          <div className="card-title">{dbName}</div>
        </div>
        <span className={`badge ${badgeCls}`}>{label}</span>
      </div>
      <textarea
        className="enrich-input"
        placeholder="Database context — what does this database store?"
        value={dbData.description || ''}
        onClick={e => e.stopPropagation()}
        onChange={e => onDescriptionChange(e.target.value, dbName)}
        onInput={handleTextareaResize}
      />
    </div>
  );
};

const TableCard = ({
  dbName, tableName, tableData, selectedTable,
  onTableClick, onDescriptionChange, onAutoEnrich,
  isGeneratingFor, isParentEnabled,
}) => {
  const displayStatus = getDisplayStatus(tableData);
  const { label, badgeCls, cardCls } = STATUS_META[displayStatus];
  const { shortName } = parseTableLabel(tableName);

  const loadId     = `${dbName}-${tableName}-`;
  const isGenerating = isGeneratingFor === loadId;
  const isDisabled   = isGenerating || !isParentEnabled;
  const colCount     = Object.keys(tableData.columns || {}).length;

  return (
    <div
      className={`card ${cardCls}${selectedTable === tableName ? ' active' : ''}`}
      onClick={() => onTableClick(tableName)}
    >
      <div className="card-header">
        <div className="card-meta">
          <div className="card-title">{shortName}</div>
          <div className="card-subtitle">{colCount} column{colCount !== 1 ? 's' : ''}</div>
        </div>
        <div className="card-actions">
          <button
            className={`ai-btn${isGenerating ? ' generating' : ''}`}
            onClick={e => {
              e.stopPropagation();
              onAutoEnrich(dbName, tableName, null, null, Object.keys(tableData.columns || {}));
            }}
            disabled={isDisabled}
            title={!isParentEnabled ? 'Add a database description first' : 'Generate AI description'}
          >
            {isGenerating ? '⏳ Generating…' : '✦ AI'}
          </button>
          <span className={`badge ${badgeCls}`}>{label}</span>
        </div>
      </div>
      <textarea
        className="enrich-input"
        placeholder={isParentEnabled ? 'What does this table store?' : 'Describe the database first…'}
        value={tableData.description || ''}
        onClick={e => e.stopPropagation()}
        onChange={e => onDescriptionChange(e.target.value, dbName, tableName)}
        onInput={handleTextareaResize}
        disabled={isDisabled}
      />
    </div>
  );
};

/* ──────────────────────────────────────────────────────────
   FK EDITOR — inline inside FieldCard
   ────────────────────────────────────────────────────────── */
function FkEditor({ dbName, tableName, colName, colData, schemaData, onFkChange }) {
  const [open,        setOpen]        = React.useState(false);
  const [draftTable,  setDraftTable]  = React.useState('');
  const [draftColumn, setDraftColumn] = React.useState('');

  const hasFk         = !!colData.fk_target;
  const suggestions   = colData.fk_suggestions || [];
  const visibleSuggestions = suggestions.filter(s => s !== colData.fk_target);

  // Tables available in the same database for manual linking
  const availableTables = Object.keys(schemaData[dbName]?.tables || {}).filter(t => t !== tableName);

  const confirm = (e) => {
    e.stopPropagation();
    if (draftTable && draftColumn) {
      onFkChange(`${draftTable}.${draftColumn}`, dbName, tableName, colName);
      setOpen(false);
      setDraftTable('');
      setDraftColumn('');
    }
  };

  const clear = (e) => {
    e.stopPropagation();
    onFkChange(null, dbName, tableName, colName);
  };

  const confirmSuggestion = (e, target) => {
    e.stopPropagation();
    onFkChange(target, dbName, tableName, colName);
  };

  return (
    <div className="fk-section" onClick={e => e.stopPropagation()}>

      {/* ── Confirmed FK chip ─────────────────────────── */}
      {hasFk && (
        <div className="fk-confirmed">
          <span className="fk-arrow">→</span>
          <span className="fk-target-label">{colData.fk_target}</span>
          <button className="fk-clear-btn" onClick={clear} title="Remove FK link">×</button>
        </div>
      )}

      {/* ── Reverse references (this column is a FK target) ── */}
      {colData.fk_sources && colData.fk_sources.length > 0 && (
        <div className="fk-referenced-by">
          <span className="fk-suggest-label">Referenced by:</span>
          <div className="fk-sources-list">
            {colData.fk_sources.map(src => (
              <span key={src} className="fk-source-chip">← {src}</span>
            ))}
          </div>
        </div>
      )}

      {/* ── Suggestions ──────────────────────────────── */}
      {!hasFk && visibleSuggestions.length > 0 && (
        <div className="fk-suggestions">
          <span className="fk-suggest-label">Suggested links:</span>
          {visibleSuggestions.map(s => (
            <button
              key={s}
              className="fk-suggest-chip"
              onClick={e => confirmSuggestion(e, s)}
              title={`Confirm FK link → ${s}`}
            >
              → {s} <span className="fk-confirm-text">Confirm</span>
            </button>
          ))}
        </div>
      )}

      {/* ── Manual editor ────────────────────────────── */}
      {!hasFk && (
        <>
          {!open ? (
            <button className="fk-add-btn" onClick={e => { e.stopPropagation(); setOpen(true); }}>
              + Add FK link
            </button>
          ) : (
            <div className="fk-editor-row">
              <select
                className="fk-select"
                value={draftTable}
                onChange={e => { setDraftTable(e.target.value); setDraftColumn(''); }}
              >
                <option value="">Table…</option>
                {availableTables.map(t => <option key={t} value={t}>{t}</option>)}
              </select>

              {draftTable && (
                <select
                  className="fk-select"
                  value={draftColumn}
                  onChange={e => setDraftColumn(e.target.value)}
                >
                  <option value="">Column…</option>
                  {Object.keys(schemaData[dbName]?.tables[draftTable]?.columns || {}).map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              )}

              <button
                className="fk-confirm-btn"
                onClick={confirm}
                disabled={!draftTable || !draftColumn}
              >
                Link
              </button>
              <button
                className="fk-cancel-btn"
                onClick={e => { e.stopPropagation(); setOpen(false); setDraftTable(''); setDraftColumn(''); }}
              >
                ×
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const FieldCard = ({
  dbName, tableName, colName, colData, selectedColumn,
  onColumnClick, onDescriptionChange, onAutoEnrich, onFkChange,
  isGeneratingFor, isParentEnabled, schemaData,
}) => {
  const displayStatus = getDisplayStatus(colData);
  const { label, badgeCls, cardCls } = STATUS_META[displayStatus];

  const loadId       = `${dbName}-${tableName}-${colName}`;
  const isGenerating = isGeneratingFor === loadId;
  const isBatchRunning = isGeneratingFor === `${dbName}-${tableName}-__ALL__`;
  const isDisabled   = isGenerating || isBatchRunning || !isParentEnabled;

  return (
    <div
      className={`card field-card ${cardCls}${selectedColumn === colName ? ' active' : ''}`}
      onClick={() => onColumnClick(colName)}
    >
      <div className="card-header">
        <div className="card-meta">
          <div className="card-title">{colName}</div>
          {colData.data_type_raw && (
            <div className="card-subtitle">{colData.data_type_raw}</div>
          )}
        </div>
        <div className="card-actions">
          <button
            className={`ai-btn${isGenerating ? ' generating' : ''}`}
            onClick={e => {
              e.stopPropagation();
              onAutoEnrich(dbName, tableName, colName, colData.data_type_raw);
            }}
            disabled={isDisabled}
            title={!isParentEnabled ? 'Add a table description first' : 'Generate AI description'}
          >
            {isGenerating ? '⏳ Generating…' : '✦ AI'}
          </button>
          <span className={`badge ${badgeCls}`}>{label}</span>
        </div>
      </div>
      <textarea
        className="enrich-input"
        placeholder={isParentEnabled ? 'Semantic description for this column…' : 'Describe the table first…'}
        value={colData.description || ''}
        onChange={e => onDescriptionChange(e.target.value, dbName, tableName, colName)}
        onClick={e => e.stopPropagation()}
        onInput={handleTextareaResize}
        disabled={isDisabled}
      />
      <FkEditor
        dbName={dbName}
        tableName={tableName}
        colName={colName}
        colData={colData}
        schemaData={schemaData}
        onFkChange={onFkChange}
      />
    </div>
  );
};

/* ──────────────────────────────────────────────────────────
   PANE COMPONENTS
   ────────────────────────────────────────────────────────── */

export function DatabasePane({ schemaData, selectedDb, onDbClick, onDescriptionChange }) {
  const dbCount = Object.keys(schemaData).length;

  return (
    <div className="pane pane-narrow">
      <div className="pane-header">
        <div className="pane-header-top">
          <span className="pane-title">Databases</span>
          <span className="pane-count">{dbCount}</span>
        </div>
        <PaneStatusSummary items={schemaData} />
      </div>
      <div className="pane-body">
        {Object.entries(schemaData).map(([dbName, dbData]) => (
          <DatabaseCard
            key={dbName}
            dbName={dbName}
            dbData={dbData}
            selectedDb={selectedDb}
            onDbClick={onDbClick}
            onDescriptionChange={onDescriptionChange}
          />
        ))}
      </div>
    </div>
  );
}

export function TablePane({
  dbName, tablesData, selectedTable,
  onTableClick, onDescriptionChange, onAutoEnrich,
  isGeneratingFor, parentDbDescription,
}) {
  const isParentEnabled = !!parentDbDescription?.trim();
  const tableCount = Object.keys(tablesData).length;

  return (
    <div className="pane pane-mid">
      <div className="pane-header">
        <div className="pane-header-top">
          <span className="pane-title">Tables</span>
          <span className="pane-count">{tableCount}</span>
        </div>
        <div className="pane-context" title={dbName}>{dbName}</div>
        <div style={{ marginTop: 6 }}>
          <PaneStatusSummary items={tablesData} />
        </div>
      </div>
      <div className="pane-body">
        {(() => {
          // ── Build schema groups ─────────────────────────────
          const groups = {};
          Object.keys(tablesData).forEach(label => {
            const { schema } = parseTableLabel(label);
            (groups[schema] = groups[schema] || []).push(label);
          });

          // Sort tables within each group alphabetically by short name
          Object.values(groups).forEach(labels =>
            labels.sort((a, b) =>
              parseTableLabel(a).shortName.toLowerCase()
                .localeCompare(parseTableLabel(b).shortName.toLowerCase())
            )
          );

          // Sort schema names: dbo always first, rest alphabetically
          const sortedGroups = Object.entries(groups).sort(([a], [b]) => {
            if (a === 'dbo') return -1;
            if (b === 'dbo') return 1;
            return a.localeCompare(b);
          });

          return sortedGroups.map(([schema, labels]) => (
            <div key={schema} className="schema-group">
              <div className="schema-group-header">
                <span className="schema-group-name">{schema}</span>
                <span className="schema-group-count">{labels.length}</span>
                <div className="schema-group-rule" />
              </div>
              {labels.map(tableName => (
                <TableCard
                  key={tableName}
                  dbName={dbName}
                  tableName={tableName}
                  tableData={tablesData[tableName]}
                  selectedTable={selectedTable}
                  onTableClick={onTableClick}
                  onDescriptionChange={onDescriptionChange}
                  onAutoEnrich={onAutoEnrich}
                  isGeneratingFor={isGeneratingFor}
                  isParentEnabled={isParentEnabled}
                />
              ))}
            </div>
          ));
        })()}
      </div>
    </div>
  );
}

export function FieldPane({
  dbName, tableName, columnsData, selectedColumn,
  onColumnClick, onDescriptionChange, onAutoEnrich, onAutoEnrichTable, onFkChange,
  isGeneratingFor, parentTableDescription, schemaData,
}) {
  const isParentEnabled = !!parentTableDescription?.trim();
  const colCount = Object.keys(columnsData).length;

  const isBatchRunning = isGeneratingFor === `${dbName}-${tableName}-__ALL__`;
  const unenrichedCount = Object.values(columnsData).filter(c => !c.description?.trim()).length;

  return (
    <div className="pane pane-wide">
      <div className="pane-header">
        <div className="pane-header-top">
          <span className="pane-title">Columns</span>
          <div className="pane-header-actions">
            <span className="pane-count">{colCount}</span>
            <button
              className={`ai-btn enrich-all-btn${isBatchRunning ? ' generating' : ''}`}
              onClick={() => onAutoEnrichTable(dbName, tableName, columnsData, parentTableDescription)}
              disabled={!isParentEnabled || isBatchRunning || (isGeneratingFor !== null && !isBatchRunning) || unenrichedCount === 0}
              title={
                !isParentEnabled        ? 'Add a table description first' :
                unenrichedCount === 0   ? 'All columns already have descriptions' :
                                          `Generate descriptions for ${unenrichedCount} unenriched column${unenrichedCount !== 1 ? 's' : ''}`
              }
            >
              {isBatchRunning
                ? '⏳ Enriching…'
                : `✦ Enrich All${unenrichedCount > 0 ? ` (${unenrichedCount})` : ''}`}
            </button>
          </div>
        </div>
        <div className="pane-context" title={tableName}>{tableName}</div>
        <div style={{ marginTop: 6 }}>
          <PaneStatusSummary items={columnsData} />
        </div>
      </div>
      <div className="pane-body">
        {Object.entries(columnsData).map(([colName, colData]) => (
          <FieldCard
            key={colName}
            dbName={dbName}
            tableName={tableName}
            colName={colName}
            colData={colData}
            selectedColumn={selectedColumn}
            onColumnClick={onColumnClick}
            onDescriptionChange={onDescriptionChange}
            onAutoEnrich={onAutoEnrich}
            onFkChange={onFkChange}
            isGeneratingFor={isGeneratingFor}
            isParentEnabled={isParentEnabled}
            schemaData={schemaData}
          />
        ))}
      </div>
    </div>
  );
}
