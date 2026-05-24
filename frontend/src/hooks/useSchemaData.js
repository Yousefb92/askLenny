import { useState, useEffect, useCallback } from 'react';

export function useSchemaData() {
  const [schemaData, setSchemaData]       = useState({});
  const [isLoading, setIsLoading]         = useState(true);
  const [error, setError]                 = useState(null);
  const [isGeneratingFor, setIsGeneratingFor] = useState(null);

  useEffect(() => {
    const fetchDiscoveryData = async () => {
      try {
        const response = await fetch('/sync/gapdiscovery');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (json.status === 'success') {
          setSchemaData(json.data);
        } else {
          throw new Error('API returned an unexpected format.');
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };
    fetchDiscoveryData();
  }, []);

  // ── Description edit ─────────────────────────────────────
  // Bug fix: transition ANY status → 'Modified' on edit, not only 'Synchronized'.
  // This ensures New items with typed descriptions surface as "Commit Pending".
  const handleDescriptionChange = (value, dbName, tableName = null, colName = null) => {
    setSchemaData(prev => {
      const next = JSON.parse(JSON.stringify(prev));

      if (colName) {
        const col = next[dbName].tables[tableName].columns[colName];
        col.description = value;
        col.status = 'Modified';
      } else if (tableName) {
        const tbl = next[dbName].tables[tableName];
        tbl.description = value;
        tbl.status = 'Modified';
      } else {
        const db = next[dbName];
        db.description = value;
        db.status = 'Modified';
      }

      return next;
    });
  };

  // ── Batch AI enrichment (all unenriched columns in one table) ────────────
  const handleAutoEnrichTable = useCallback(async (dbName, tableName, columnsData, tableDescription) => {
    // Collect only columns that have no description yet — never overwrite existing work
    const toEnrich = Object.entries(columnsData)
      .filter(([, col]) => !col.description?.trim())
      .map(([colName, col]) => ({ name: colName, data_type: col.data_type_raw || 'unknown' }));

    if (toEnrich.length === 0) return;

    setIsGeneratingFor(`${dbName}-${tableName}-__ALL__`);
    try {
      const res = await fetch('/sync/enrich_table', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          db_name: dbName,
          table_name: tableName,
          table_description: tableDescription || '',
          columns: toEnrich,
        }),
      });
      if (!res.ok) throw new Error('Batch enrichment failed');
      const json = await res.json();
      if (json.status === 'success') {
        // Single state update for all returned descriptions
        setSchemaData(prev => {
          const next = JSON.parse(JSON.stringify(prev));
          Object.entries(json.descriptions).forEach(([colName, description]) => {
            const col = next[dbName]?.tables[tableName]?.columns[colName];
            if (col) {
              col.description = description;
              col.status = 'Modified';
            }
          });
          return next;
        });
      }
    } catch (err) {
      throw err;
    } finally {
      setIsGeneratingFor(null);
    }
  }, []);

  // ── AI enrichment ─────────────────────────────────────────
  const handleAutoEnrich = async (dbName, tableName, colName, dataType, tableColumns = null) => {
    const loadId = `${dbName}-${tableName || ''}-${colName || ''}`;
    setIsGeneratingFor(loadId);
    try {
      const response = await fetch('/sync/enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          db_name: dbName,
          table_name: tableName,
          column_name: colName,
          data_type: dataType,
          table_columns: tableColumns,
        }),
      });
      if (!response.ok) throw new Error('AI generation failed');
      const json = await response.json();
      if (json.status === 'success') {
        handleDescriptionChange(json.description, dbName, tableName, colName);
      }
    } catch (err) {
      console.error(err);
      throw err; // let the caller handle the toast
    } finally {
      setIsGeneratingFor(null);
    }
  };

  // ── FK link management ───────────────────────────────────
  // Sets or clears the confirmed FK target on a column.
  // Marks the column Modified so it is included in the next commit,
  // which will create the FK edge in the Rust graph.
  const handleFkChange = (target, dbName, tableName, colName) => {
    setSchemaData(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const col  = next[dbName].tables[tableName].columns[colName];
      col.fk_target = target || null;
      col.status    = 'Modified';
      return next;
    });
  };

  // ── Post-commit state reset ───────────────────────────────
  // Bug fix: after a successful commit, flip all Modified → Synchronized
  // so the UI correctly reflects the committed state.
  const resetAfterCommit = () => {
    setSchemaData(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      Object.values(next).forEach(db => {
        if (db.status === 'Modified') db.status = 'Synchronized';
        Object.values(db.tables || {}).forEach(tbl => {
          if (tbl.status === 'Modified') tbl.status = 'Synchronized';
          Object.values(tbl.columns || {}).forEach(col => {
            if (col.status === 'Modified') col.status = 'Synchronized';
          });
        });
      });
      return next;
    });
  };

  return {
    schemaData,
    isLoading,
    error,
    isGeneratingFor,
    handleDescriptionChange,
    handleAutoEnrich,
    handleAutoEnrichTable,
    handleFkChange,
    resetAfterCommit,
  };
}
