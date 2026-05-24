"""
query_service.py
────────────────
Full RAG-to-SQL pipeline:
  1. Embed the question via llm_client.get_vector_embedding
  2. Vector search the Rust engine → GraphRAG context (semantically matched nodes)
  3. Enrich the context:
       a. Identify every table referenced in the matched column labels
       b. Scan column descriptions for FK hints that mention other tables
       c. Append the FULL column listing of every relevant table so the LLM
          has everything it needs to write JOINs / subqueries
  4. Generate dialect-accurate SQL via Gemini (gemini-2.5-flash)
  5. Execute the SQL against the source database and return the result set
"""

import re
import zlib
import pyodbc
from decimal import Decimal
from datetime import datetime, date

import google.generativeai as genai

from core.config import config
from clients import llm_client, rust_client

# ──────────────────────────────────────────────────────────────
# SQL generation prompt — reused verbatim from test_search.py
# ──────────────────────────────────────────────────────────────
_SQL_PROMPT_TEMPLATE = """\
You are an expert SQL Database Administrator.
Your task is to write a highly optimized SQL query to answer the user's question \
based strictly on the target architecture.

CRITICAL RULES:
1. ONLY use the tables and columns provided in the schema context below.
2. If the schema provided does not contain enough information to answer the question, \
output exactly: "I do not have enough database context to write this query." \
Do NOT hallucinate table names.
3. Return ONLY the raw SQL code. No explanation, no conversational text.
4. Do NOT wrap your output in markdown syntax (like ```sql). Just return raw text.

DIALECT AND TYPE RULES:
5. Pay close attention to the "Engine Dialect" field provided for the Database/Table \
nodes. You MUST write the query using the native syntax and system functions of that engine.
   - Microsoft SQL Server: use TOP instead of LIMIT, GETDATE() instead of NOW(), \
DATEADD() for date arithmetic.
   - PostgreSQL: use LIMIT, NOW() or CURRENT_TIMESTAMP, :: for casting.
6. Inspect the "Data Type" of each column. Ensure comparisons, WHERE clauses, and \
string functions align with those specific types.

Assembled Database Graph Context:
{graphrag_context}

User Question: {question}
SQL Query:"""

_DATA_TYPE_LABELS = {
    0: 'UNKNOWN', 1: 'INT/INTEGER', 2: 'VARCHAR/NVARCHAR',
    3: 'DATETIME/DATE', 4: 'DECIMAL/NUMERIC', 5: 'BIT/BOOLEAN',
}

# Use the same model as test_search.py for SQL generation
_sql_model = genai.GenerativeModel("gemini-2.5-flash")


# ──────────────────────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────────────────────
def _safe(val):
    """Convert a single cell value to a JSON-safe type."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, bytes):
        return val.hex()
    return val


# ──────────────────────────────────────────────────────────────
# QueryService
# ──────────────────────────────────────────────────────────────
class QueryService:

    # ── Config helpers ────────────────────────────────────────

    def _get_connector(self, db_name: str):
        for c in config.connectors:
            if c.database == db_name:
                return c
        return None

    def _hashed_id(self, connector) -> int:
        """Reproduces the same zlib.adler32 hash used in processor.py."""
        return zlib.adler32(connector.id.encode("utf-8"))

    def _connect(self, connector):
        conn_str = (
            f"DRIVER={{SQL Server}};"
            f"SERVER={connector.server};"
            f"DATABASE={connector.database};"
            f"UID={connector.username};"
            f"PWD={connector.password_env_var}"
        )
        return pyodbc.connect(conn_str)

    # ── Context enrichment ────────────────────────────────────

    def _enrich_context(self, graphrag_context: str, source_id: int) -> str:
        """
        The Rust vector search returns the *semantically closest* column nodes but
        does not traverse upward to sibling columns or outward to FK-related tables.
        This function compensates entirely in Python:

        1. Extract table names from matched column labels  ("Orders.UserID" → "Orders")
        2. Scan column descriptions for FK hints          ("foreign key to the users table" → "Users")
        3. Fetch all nodes for this source_id from Rust
        4. For every relevant table, append the FULL column listing to the context

        The LLM then has everything it needs to write JOINs and subqueries correctly.
        """
        # --- Step 1: tables directly referenced in matched labels ---
        # Handles both 2-part labels (dbo): "Orders.CustomerID" → "Orders"
        # and 3-part schema-qualified labels: "Sales.SalesOrderHeader.SalesOrderID"
        #                                       → "Sales.SalesOrderHeader"
        # ([\w.]+) is greedy and backtracks so the final \.\w+ always anchors on the
        # last dot, giving us everything before the column name.
        relevant_tables = set(
            m.group(1)
            for m in re.finditer(r'Label:\s+([\w.]+)\.\w+', graphrag_context)
        )

        if not relevant_tables:
            return graphrag_context

        # --- Step 2: FK hints in descriptions ---
        # e.g. "foreign key … linking to the users table" → add Users
        description_text = ' '.join(re.findall(r'Description:\s*(.+)', graphrag_context))

        try:
            all_nodes = rust_client.get_all_nodes()
        except Exception as e:
            print(f"[QueryService] Could not fetch all nodes for context enrichment: {e}")
            return graphrag_context

        nodes_for_db = [n for n in all_nodes if n.get('source_id') == source_id]

        # Index table nodes by their label
        table_nodes = {
            n['label']: n
            for n in nodes_for_db
            if n.get('category') == 1
        }

        # Scan description text for any table name that appears as a word
        for t_name in table_nodes:
            if re.search(rf'\b{re.escape(t_name)}\b', description_text, re.IGNORECASE):
                relevant_tables.add(t_name)
                print(f"[QueryService] FK hint detected → expanding context to include '{t_name}'")

        # DB node for display label
        db_node = next((n for n in nodes_for_db if n.get('category') == 0), {})
        db_label = db_node.get('label', 'Database')

        # --- Step 3: build supplementary full-schema block ---
        lines = [
            "",
            "══════════════════════════════════════════════════════",
            "SUPPLEMENTARY FULL TABLE SCHEMAS",
            "(Use these for JOIN conditions, subqueries, and column selection)",
            "══════════════════════════════════════════════════════",
        ]

        added_any = False
        for table_name in sorted(relevant_tables):
            prefix = f"{table_name}."
            cols = [
                n for n in nodes_for_db
                if n.get('category') == 2
                and n.get('label', '').startswith(prefix)
            ]
            if not cols:
                continue

            added_any = True
            t_node   = table_nodes.get(table_name, {})
            t_desc   = t_node.get('description', '')

            lines.append(f"\n[Table] {table_name}  (Database: {db_label})")
            if t_desc:
                lines.append(f"  Purpose: {t_desc}")
            lines.append("  Columns:")

            for col in sorted(cols, key=lambda c: c.get('label', '')):
                # rsplit so we always get just the column name, regardless of
                # whether the label is "Table.Col" or "Schema.Table.Col"
                short_name = col['label'].rsplit('.', 1)[-1]
                dt_label   = _DATA_TYPE_LABELS.get(col.get('data_type', 0), 'UNKNOWN')
                col_desc   = col.get('description', '')
                line       = f"    - {short_name}  ({dt_label})"
                if col_desc:
                    line += f":  {col_desc}"
                lines.append(line)

        if not added_any:
            return graphrag_context

        enriched = graphrag_context + '\n'.join(lines)
        print(f"[QueryService] Context enriched: {len(graphrag_context)} → {len(enriched)} chars "
              f"(added schemas for: {', '.join(sorted(relevant_tables))})")
        return enriched

    # ── Core pipeline ──────────────────────────────────────────

    def ask(self, question: str, db_name: str, limit: int = 10) -> dict:
        """
        Full end-to-end query:
          embed → vector search → enrich context → generate SQL → execute → return.
        """
        connector = self._get_connector(db_name)
        if not connector:
            raise ValueError(f"No connector configured for database '{db_name}'")

        source_id = self._hashed_id(connector)
        print(f"[QueryService] ask() — db='{db_name}'  source_id={source_id}  limit={limit}")

        # 1. Embed the question
        print("[QueryService] Generating embedding…")
        query_vector = llm_client.get_vector_embedding(question)

        # 2. Vector search → base GraphRAG context
        print("[QueryService] Calling Rust vector search…")
        search_result = rust_client.vector_search(query_vector, source_id, limit)
        graphrag_context = search_result.get("graphrag_context", "")

        if not graphrag_context:
            raise ValueError(
                "The Rust engine returned no schema context. "
                "Make sure schema data has been committed to the graph for this database."
            )

        # 3. Enrich with full table schemas + FK-hinted related tables
        graphrag_context = self._enrich_context(graphrag_context, source_id)

        print(f"[QueryService] Generating SQL…")

        # 4. Generate SQL
        prompt = _SQL_PROMPT_TEMPLATE.format(
            graphrag_context=graphrag_context,
            question=question,
        )
        response = _sql_model.generate_content(prompt)
        sql = response.text.strip()

        print(f"[QueryService] SQL generated:\n{sql}")

        if sql.lower().startswith("i do not have enough"):
            return {"sql": sql, "columns": [], "rows": [], "row_count": 0}

        # 5. Execute
        columns, rows, row_count = self._execute(connector, sql)
        print(f"[QueryService] Done — {row_count} rows returned.")

        return {"sql": sql, "columns": columns, "rows": rows, "row_count": row_count}

    def execute(self, sql: str, db_name: str) -> dict:
        """Re-execute a pre-generated SQL statement (↺ Re-run)."""
        connector = self._get_connector(db_name)
        if not connector:
            raise ValueError(f"No connector configured for database '{db_name}'")
        columns, rows, row_count = self._execute(connector, sql)
        return {"columns": columns, "rows": rows, "row_count": row_count}

    # ── SQL execution ──────────────────────────────────────────

    def _execute(self, connector, sql: str):
        conn = self._connect(connector)
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description is None:
                row_count = cursor.rowcount
                conn.commit()
                return [], [], row_count

            columns = [col[0] for col in cursor.description]
            raw_rows = cursor.fetchall()
            rows = [[_safe(cell) for cell in row] for row in raw_rows]
            return columns, rows, len(rows)
        finally:
            conn.close()
