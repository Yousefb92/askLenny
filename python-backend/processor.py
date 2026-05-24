import os
import pyodbc
from dotenv import load_dotenv
import zlib
from core.config import config

load_dotenv()

RUST_API = config.rust_engine_url

# ── Type helpers ──────────────────────────────────────────────────────────────

def _base_type(raw: str) -> str:
    """'varchar(255)' → 'varchar'"""
    return raw.lower().split("(")[0].strip()

_TYPE_FAMILY = {
    "int": "int", "bigint": "int", "smallint": "int", "tinyint": "int",
    "varchar": "str", "nvarchar": "str", "char": "str", "nchar": "str",
    "text": "str", "ntext": "str",
    "uniqueidentifier": "guid",
    "datetime": "date", "datetime2": "date", "date": "date", "smalldatetime": "date",
    "decimal": "num", "numeric": "num", "float": "num", "real": "num", "money": "num",
    "bit": "bit",
}

def _type_family(raw: str) -> str:
    return _TYPE_FAMILY.get(_base_type(raw), "other")


def _table_label(schema: str, table: str) -> str:
    """
    Produce the canonical label used for both the tables dict key and the
    Rust graph node label.

    dbo tables keep their bare name for backward compatibility:
        'dbo', 'Orders'  →  'Orders'
    All other schemas are schema-qualified:
        'Sales', 'SalesOrderHeader'  →  'Sales.SalesOrderHeader'
    """
    return table if schema.lower() == "dbo" else f"{schema}.{table}"


# ── Schema SQL helpers ────────────────────────────────────────────────────────

def _schema_filter_sql(connector, alias: str = "") -> str:
    """
    Return the WHERE fragment that limits rows to the desired schemas.

    If the connector lists explicit schemas, use TABLE_SCHEMA IN (...).
    Otherwise exclude the system-reserved schemas every SQL Server has.
    """
    col = f"{alias}.TABLE_SCHEMA" if alias else "TABLE_SCHEMA"
    if connector.schemas:
        quoted = ", ".join(f"'{s}'" for s in connector.schemas)
        return f"{col} IN ({quoted})"
    else:
        return f"{col} NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest', 'db_owner', 'db_accessadmin')"


# ── Main discovery function ───────────────────────────────────────────────────

def generate_multi_db_proposal():
    import requests
    full_report = {}

    # Fetch current Rust node and edge state once (outside the connector loop)
    try:
        rust_nodes = requests.get(f"{RUST_API}/schema/nodes").json()
    except Exception as e:
        print(f"Error: Could not connect to Rust API: {e}")
        rust_nodes = []

    try:
        rust_fk_edges = [
            e for e in requests.get(f"{RUST_API}/schema/edges").json()
            if e.get("edge_type") == 3
        ]
        print(f"Fetched {len(rust_fk_edges)} FK edge(s) from graph.")
    except Exception as e:
        print(f"Warning: Could not fetch edges from Rust API: {e}")
        rust_fk_edges = []

    for connector in config.connectors:
        db_name    = connector.database
        raw_source = connector.id
        hashed_id  = zlib.adler32(raw_source.encode("utf-8"))

        print(f"--- Analysing {db_name} (ID: {raw_source} → Hash: {hashed_id}) ---")

        password = connector.password
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={connector.server};"
            f"DATABASE={db_name};"
            f"UID={connector.username};"
            f"PWD={password};"
            f"TrustServerCertificate=yes"
        )

        try:
            conn   = pyodbc.connect(conn_str)
            cursor = conn.cursor()

            # ── Column discovery ──────────────────────────────
            schema_filter = _schema_filter_sql(connector)
            print(schema_filter)
            cursor.execute(f"""
                SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM   INFORMATION_SCHEMA.COLUMNS
                WHERE  {schema_filter}
                ORDER  BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """)
            sql_rows = cursor.fetchall()
            print(f"    Columns found: {len(sql_rows)}")

            # ── Explicit FK discovery (hard constraints) ──────
            # Pull schema info for both the child (FK) and parent (PK) sides so
            # we can construct schema-qualified labels consistently.
            try:
                schema_filter_fk = _schema_filter_sql(connector, alias="kcu_fk")
                cursor.execute(f"""
                    SELECT
                        kcu_fk.TABLE_SCHEMA  AS child_schema,
                        kcu_fk.TABLE_NAME    AS child_table,
                        kcu_fk.COLUMN_NAME   AS child_column,
                        kcu_pk.TABLE_SCHEMA  AS parent_schema,
                        kcu_pk.TABLE_NAME    AS parent_table,
                        kcu_pk.COLUMN_NAME   AS parent_column
                    FROM  INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                    INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu_fk
                        ON  rc.CONSTRAINT_NAME        = kcu_fk.CONSTRAINT_NAME
                        AND rc.CONSTRAINT_SCHEMA      = kcu_fk.CONSTRAINT_SCHEMA
                    INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu_pk
                        ON  rc.UNIQUE_CONSTRAINT_NAME = kcu_pk.CONSTRAINT_NAME
                        AND rc.UNIQUE_CONSTRAINT_SCHEMA = kcu_pk.CONSTRAINT_SCHEMA
                    WHERE {schema_filter_fk}
                """)
                explicit_fks = {}
                for row in cursor.fetchall():
                    child_schema, child_table, child_col, parent_schema, parent_table, parent_col = row
                    child_label  = _table_label(child_schema,  child_table)
                    parent_label = _table_label(parent_schema, parent_table)
                    # Key: (table_label, col_name)  →  Value: "ParentLabel.ParentCol"
                    explicit_fks[(child_label, child_col)] = f"{parent_label}.{parent_col}"
                print(f"    Explicit FKs found: {len(explicit_fks)}")
            except Exception as e:
                print(f"    FK query failed (non-critical): {e}")
                explicit_fks = {}

        except Exception as e:
            print(f"    SQL Connection Error for {db_name}: {e}")
            continue

        # ── Rust node buckets ─────────────────────────────────
        db_nodes    = {n["label"]: n for n in rust_nodes if n.get("source_id") == hashed_id and n.get("category") == 0}
        table_nodes = {n["label"]: n for n in rust_nodes if n.get("source_id") == hashed_id and n.get("category") == 1}
        col_nodes   = {n["label"]: n for n in rust_nodes if n.get("source_id") == hashed_id and n.get("category") == 2}

        # ── Build DB proposal ─────────────────────────────────
        db_node     = db_nodes.get(db_name, {})
        db_proposal = {
            "source_id":   raw_source,
            "hashed_id":   hashed_id,
            "status":      "Synchronized" if db_name in db_nodes else "New",
            "description": db_node.get("description", ""),
            "tables":      {},
        }

        for row in sql_rows:
            t_schema, t_name, c_name, d_type = row
            t_label = _table_label(t_schema, t_name)    # canonical label / dict key

            if t_label not in db_proposal["tables"]:
                t_node = table_nodes.get(t_label, {})
                db_proposal["tables"][t_label] = {
                    "status":      "Synchronized" if t_label in table_nodes else "New",
                    "description": t_node.get("description", ""),
                    "columns":     {},
                }

            # Column FQN follows the same label convention so it stays consistent
            # across processor ↔ sync_service ↔ Rust graph.
            #   dbo:     "Orders.CustomerID"
            #   non-dbo: "Sales.SalesOrderHeader.SalesOrderID"
            fqn    = f"{t_label}.{c_name}"
            c_node = col_nodes.get(fqn, {})
            confirmed_fk = explicit_fks.get((t_label, c_name))

            db_proposal["tables"][t_label]["columns"][c_name] = {
                "status":        "Synchronized" if fqn in col_nodes else "New",
                "description":   c_node.get("description", ""),
                "data_type_raw": d_type,
                "category":      2,
                "fk_target":     confirmed_fk,   # "ParentLabel.ParentCol" or None
                "fk_suggestions": [],            # filled in below
                "fk_sources":    [],             # reverse refs, filled in below
            }

        # ── Graph FK restoration pass ─────────────────────────
        # Read confirmed FK edges committed to Rust (edge_type=3) and restore
        # fk_target on child columns.  This makes manually-confirmed FK links
        # survive page reloads — they were committed as Rust edges and now come
        # back through the graph rather than INFORMATION_SCHEMA.
        #
        # Graph edges take precedence over INFORMATION_SCHEMA because they
        # reflect explicit user decisions (manual links or user-confirmed suggestions).
        col_id_to_fqn = {
            n["id"]: n["label"]
            for n in rust_nodes
            if n.get("source_id") == hashed_id and n.get("category") == 2
        }

        for edge in rust_fk_edges:
            if edge.get("source_db_id") != hashed_id:
                continue
            child_fqn  = col_id_to_fqn.get(edge["from_node_id"])
            parent_fqn = col_id_to_fqn.get(edge["to_node_id"])
            if not child_fqn or not parent_fqn:
                continue

            dot = child_fqn.rfind('.')
            if dot == -1:
                continue
            child_t = child_fqn[:dot]
            child_c = child_fqn[dot + 1:]

            if (child_t in db_proposal["tables"] and
                    child_c in db_proposal["tables"][child_t]["columns"]):
                db_proposal["tables"][child_t]["columns"][child_c]["fk_target"] = parent_fqn
                print(f"    Restored FK (graph edge): {child_fqn} → {parent_fqn}")

        # ── fk_sources backfill pass ──────────────────────────
        # After all fk_target values are settled (INFORMATION_SCHEMA + graph edges),
        # walk every confirmed link and stamp the parent column's fk_sources list
        # so the UI can show "Referenced by …" on the parent side.
        for t_label, t_data in db_proposal["tables"].items():
            for c_name, c_data in t_data["columns"].items():
                fk_target = c_data.get("fk_target")
                if not fk_target:
                    continue
                dot = fk_target.rfind('.')
                if dot == -1:
                    continue
                parent_t = fk_target[:dot]
                parent_c = fk_target[dot + 1:]
                if (parent_t in db_proposal["tables"] and
                        parent_c in db_proposal["tables"][parent_t]["columns"]):
                    db_proposal["tables"][parent_t]["columns"][parent_c] \
                        .setdefault("fk_sources", []) \
                        .append(f"{t_label}.{c_name}")

        # ── Implicit FK suggestion pass ───────────────────────
        # Index: normalised_col_name → { type_family → [(table_label, col_name)] }
        # Columns sharing the same short name AND type family across ≥2 tables are
        # surfaced as candidate FK links for the user to confirm.
        name_index: dict[str, dict[str, list]] = {}
        for t_label, t_data in db_proposal["tables"].items():
            for c_name, c_data in t_data["columns"].items():
                key    = c_name.lower()
                family = _type_family(c_data["data_type_raw"])
                name_index.setdefault(key, {}).setdefault(family, []).append((t_label, c_name))

        for name_key, family_map in name_index.items():
            for family, occurrences in family_map.items():
                if len(occurrences) < 2:
                    continue
                for (t_label, c_name) in occurrences:
                    col_entry = db_proposal["tables"][t_label]["columns"][c_name]
                    if col_entry.get("fk_target"):
                        continue   # already the child side of a confirmed FK, skip

                    # Build the already-linked set for this column:
                    # anything already in fk_sources means this column IS the
                    # parent side of that relationship — don't suggest it again
                    # in reverse.
                    already_linked = set(col_entry.get("fk_sources") or [])

                    others = [
                        f"{ot}.{oc}"
                        for ot, oc in occurrences
                        if ot != t_label
                        and f"{ot}.{oc}" not in already_linked
                    ]
                    if others:
                        col_entry["fk_suggestions"] = others

        full_report[db_name] = db_proposal
        conn.close()

    return full_report
