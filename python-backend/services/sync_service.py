# services/sync_service.py
from clients import rust_client, llm_client

DATA_TYPE_MAP = {
    "unknown": 0,
    "int": 1,
    "integer": 1,
    "bigint": 1,
    "varchar": 2,
    "nvarchar": 2,
    "text": 2,
    "string": 2,
    "datetime": 3,
    "date": 3,
    "timestamp": 3,
    "decimal": 4,
    "numeric": 4,
    "float": 4,
    "bit": 5,
    "boolean": 5
}

# Map source system strings to your Rust Engine integers
ENGINE_TYPE_MAP = {
    "unknown": 0,
    "sqlserver": 1,
    "sqlexpress": 1,
    "mssql": 1,
    "postgresql": 2,
    "mysql": 3,
    "snowflake": 4
}

class GraphSyncService:
    def __init__(self):
        self.nodes_created = 0
        self.nodes_updated = 0
        self.edges_created = 0
        self.graph_cache = {}
        self.existing_fk_edges: set[tuple[int, int]] = set()  # (from_node_id, to_node_id)

    def _build_cache(self):
        """
        Loads all existing Rust nodes into an O(1) memory dictionary.
        Also builds the existing_fk_edges set so _process_fk_edges can
        skip pairs that are already linked, preventing duplicate edges.
        """
        rust_nodes = rust_client.get_all_nodes()
        for node in rust_nodes:
            key = (node.get("label"), node.get("category"))
            self.graph_cache[key] = (node.get("id"), (node.get("description") or "").strip())

        rust_edges = rust_client.get_all_edges()
        self.existing_fk_edges = {
            (e["from_node_id"], e["to_node_id"])
            for e in rust_edges
            if e.get("edge_type") == 3
        }
        print(f"Cache built: {len(self.graph_cache)} nodes, {len(self.existing_fk_edges)} existing FK edges.")

    def process_payload(self, payload: dict) -> dict:
        """The main entry point for the sync loop."""
        self._build_cache()

        # Pass 1: nodes and containment edges (Database → Table → Column)
        for db_name, db_data in payload.items():
            db_id, engine_type = self._process_database(db_name, db_data)
            print(f"Database node processed: {db_id}")

            source_id = db_data.get("hashed_id", 1)

            for table_name, table_data in db_data.get("tables", {}).items():
                self._process_table(
                    table_name=table_name,
                    table_data=table_data,
                    db_id=db_id,
                    source_db_id=source_id,
                    engine_type=engine_type,
                )

        # Pass 2: FK edges — must run AFTER all column nodes exist in the cache
        fk_created = self._process_fk_edges(payload)

        return {
            "status": "success",
            "message": (
                f"Graph Sync Complete! "
                f"Created {self.nodes_created} nodes, "
                f"updated {self.nodes_updated}, "
                f"created {self.edges_created} containment edges and {fk_created} FK edges."
            ),
        }

    def _process_fk_edges(self, payload: dict) -> int:
        """
        Second pass: walk every column that carries a confirmed fk_target and
        create a FK edge (edge_type=3) between the child column node and the
        parent column node.

        fk_target format: "ParentTable.ParentColumn"  (same database)

        The graph_cache already contains every node committed in Pass 1, so
        both endpoints of each FK edge can be resolved without extra API calls.
        """
        fk_count = 0

        for db_name, db_data in payload.items():
            source_db_id = db_data.get("hashed_id", 1)

            for table_name, table_data in db_data.get("tables", {}).items():
                for col_name, col_data in table_data.get("columns", {}).items():
                    fk_target = col_data.get("fk_target")
                    if not fk_target:
                        continue

                    # FQN keys match how nodes are stored in the cache
                    fqn_child  = f"{table_name}.{col_name}"     # e.g. "Orders.UserID"
                    fqn_parent = fk_target                       # e.g. "Users.UserID"

                    child_key  = (fqn_child,  2)
                    parent_key = (fqn_parent, 2)

                    if child_key not in self.graph_cache:
                        print(f"⚠️  FK skip: child node '{fqn_child}' not in graph (not yet committed?)")
                        continue
                    if parent_key not in self.graph_cache:
                        print(f"⚠️  FK skip: parent node '{fqn_parent}' not found — check it belongs to the same database and has been committed")
                        continue

                    child_node_id  = self.graph_cache[child_key][0]
                    parent_node_id = self.graph_cache[parent_key][0]

                    # Skip if this FK edge already exists in the graph
                    if (child_node_id, parent_node_id) in self.existing_fk_edges:
                        print(f"⏭  FK edge already exists: {fqn_child} → {fqn_parent}, skipping")
                        continue

                    try:
                        rust_client.create_edge(
                            source_id=child_node_id,
                            target_id=parent_node_id,
                            source_db_id=source_db_id,
                            edge_type=3,   # FK relationship
                        )
                        fk_count += 1
                        self.existing_fk_edges.add((child_node_id, parent_node_id))  # update in-flight
                        print(f"✅ FK edge: {fqn_child} → {fqn_parent}")
                    except Exception as e:
                        print(f"❌ FK edge failed ({fqn_child} → {fqn_parent}): {e}")

        return fk_count

    def _process_database(self, db_name: str, db_data: dict) -> int:
        """Handles lookup, creation, or updating of a single Database node."""
        source_id = db_data.get("hashed_id", 1)
        db_desc = (db_data.get("description") or "").strip()
        db_key = (db_name, 0)  # Category 0 = DB

        # 1. Calculate DB Engine mapping immediately
        raw_source_str = db_data.get("source_id", "unknown").lower()
        mapped_engine_type = 0
        for key, val in ENGINE_TYPE_MAP.items():
            if key in raw_source_str:
                mapped_engine_type = val
                break

        print(f"Database source id: {source_id} Engine: {mapped_engine_type})")

        if db_key in self.graph_cache:
            db_id, old_desc = self.graph_cache[db_key]
            print(f"Database '{db_name}' cached hit at index {db_id}")

            if old_desc != db_desc:
                print(f"Updating description for Database: {db_name}")
                rust_client.update_node_description(db_id, db_desc)
                self.nodes_updated += 1
            else:
                print('Database Node description has not changed - mutation not required')

            return db_id, mapped_engine_type

        else:
            print(f"Database '{db_name}' is brand new. Computing embedding...")
            db_vector = llm_client.get_vector_embedding(db_desc if db_desc else db_name)

            db_id = rust_client.create_node(
                label=db_name,
                description=db_desc,
                category=0,
                data_type=0,
                engine_type=mapped_engine_type,
                source_id=source_id,
                embedding=db_vector
            )

            # Add it to our local cache mid-flight so table loops can see it later
            self.graph_cache[db_key] = (db_id, db_desc)
            self.nodes_created += 1
            return db_id, mapped_engine_type

    def _process_table(self, table_name: str, table_data: dict, db_id: int, source_db_id: int, engine_type: int):
        """Handles lookup, creation, or updating of a Table node and its Columns."""
        table_desc = (table_data.get("description") or "").strip()
        table_status = table_data.get("status", "New")
        table_key = (table_name, 1)  # Category 1 = Table

        # --- THE TABLE BOUNCER ---
        # If it's new and has no text, completely skip this table and its columns!
        if table_status == "New" and not table_desc:
            print(f"Skipping empty New Table: {table_name}")
            return

            # 1. Process the Table Node
        if table_key in self.graph_cache:
            t_id, old_desc = self.graph_cache[table_key]

            # Use the explicit status flag (or text comparison fallback)
            if table_status == "Modified" or old_desc != table_desc:
                print(f"Updating description for Table: {table_name}")
                rust_client.update_node_description(t_id, table_desc)
                self.nodes_updated += 1
            else:
                print(f"No changes required for Table: {table_name}")
        else:
            print(f"Table '{table_name}' is brand new. Computing embedding...")
            table_vector = llm_client.get_vector_embedding(table_desc if table_desc else table_name)

            t_id = rust_client.create_node(
                label=table_name,
                description=table_desc,
                category=1,
                data_type=0,
                engine_type=engine_type,
                source_id=source_db_id,
                embedding=table_vector
            )

            self.graph_cache[table_key] = (t_id, table_desc)
            self.nodes_created += 1

            # Create Edge: Database -> Table (Edge Type 1)
            rust_client.create_edge(source_id=db_id, target_id=t_id, source_db_id=source_db_id, edge_type=1)
            self.edges_created += 1

        # 2. Process the Column Nodes associated with this Table
        for col_name, col_data in table_data.get("columns", {}).items():
            col_desc = (col_data.get("description") or "").strip()
            col_status = col_data.get("status", "New")

            # --- THE COLUMN BOUNCER ---
            # If it's new and has no text, skip to the next column
            if col_status == "New" and not col_desc:
                print(f"Skipping empty Column: {col_name}")
                continue

            # Construct FQN to prevent dictionary collisions!
            fqn_col_name = f"{table_name}.{col_name}"
            col_key = (fqn_col_name, 2)  # Category 2 = Column

            if col_key in self.graph_cache:
                col_id, old_desc = self.graph_cache[col_key]

                if col_status == "Modified" or old_desc != col_desc:
                    print(f"Updating description for Column: {fqn_col_name}")
                    rust_client.update_node_description(col_id, col_desc)
                    self.nodes_updated += 1
            else:
                print(f"Creating new Column Node: {fqn_col_name}")
                col_vector = llm_client.get_vector_embedding(col_desc if col_desc else col_name)

                # 1. Calculate the mapped value FIRST
                raw_type = col_data.get("data_type_raw", "unknown").lower()
                mapped_data_type = DATA_TYPE_MAP.get(raw_type, 0)

                # 2. Construct the payload dictionary using the calculated variable
                node_payload = {
                    "label": fqn_col_name,
                    "description": col_desc,
                    "category": 2,
                    "data_type": mapped_data_type,
                    "engine_type": engine_type,
                    "source_id": source_db_id,
                    "embedding": col_vector
                }

                # 3. Safely print it for debugging (hiding the massive vector array)
                debug_payload = node_payload.copy()
                debug_payload["embedding"] = f"<Vector of length {len(col_vector)}>"
                print(f"DEBUG - About to send Column payload to Rust: {debug_payload}")

                # 4. Unpack the dictionary directly into the function arguments
                col_id = rust_client.create_node(**node_payload)

                self.graph_cache[col_key] = (col_id, col_desc)
                self.nodes_created += 1

                # Create Edge: Table -> Column (Edge Type 2)
                rust_client.create_edge(source_id=t_id, target_id=col_id, source_db_id=source_db_id, edge_type=2)
                self.edges_created += 1