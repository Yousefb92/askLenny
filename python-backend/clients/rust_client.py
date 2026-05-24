# clients/rust_client.py
import requests
from fastapi import HTTPException
from core.config import config


def get_all_nodes() -> list[dict]:
    """Fetches all nodes from the Rust engine to build the cache."""
    res = requests.get(f"{config.rust_engine_url}/schema/nodes")
    return res.json() if res.status_code == 200 else []


def get_all_edges() -> list[dict]:
    """
    Fetches every edge from the Rust engine.
    Each item: { from_node_id, to_node_id, edge_type, source_db_id }
    Used to restore FK state on discovery reload and to skip duplicate edges on commit.
    """
    res = requests.get(f"{config.rust_engine_url}/schema/edges")
    return res.json() if res.status_code == 200 else []


def create_node(label: str, description: str, category: int, data_type: int, engine_type: int, source_id: int,
                embedding: list[float]) -> int:
    """Creates a new node in the Rust binary map and returns its ID."""
    payload = {
        "label": label,
        "description": description,
        "category": category,
        "data_type": data_type,
        "engine_type": engine_type,
        "source_id": source_id,
        "is_pk": 0,
        "embedding": embedding
    }
    res = requests.post(f"{config.rust_engine_url}/schema/node", json=payload)

    if res.status_code not in [200, 201]:
        print(f"❌ Rust Engine rejected the request with HTTP Status {res.status_code}!")
        print(f"Raw response text from Rust: {res.text}")
        raise HTTPException(status_code=500, detail=f"Rust creation error: {res.text}")

    return res.json().get("node_id")


def update_node_description(node_id: int, description: str):
    """Appends a new description to the Rust string heap for an existing node."""
    payload = {
        "node_id": node_id,
        "description": description
    }
    res = requests.post(f"{config.rust_engine_url}/node/updateDescription", json=payload)

    if res.status_code != 200:
        print(f"❌ Rust Engine rejected the update with HTTP {res.status_code}!")
        print(f"Raw response: {res.text}")
        raise HTTPException(status_code=500, detail=f"Rust update error: {res.text}")


def vector_search(query_embedding: list[float], source_id: int, limit: int = 5) -> dict:
    """
    Sends a query embedding to the Rust engine and returns the closest matching
    nodes along with the assembled GraphRAG context string.

    Returns: { "matched_node_ids": [...], "graphrag_context": "..." }
    """
    payload = {
        "query_embedding": query_embedding,
        "limit": limit,
        "source_id": source_id,
    }
    res = requests.post(f"{config.rust_engine_url}/query/vector_search", json=payload)

    if res.status_code != 200:
        print(f"❌ Rust vector search failed with HTTP {res.status_code}: {res.text}")
        raise HTTPException(status_code=502, detail=f"Rust vector search error: {res.text}")

    return res.json()


def create_edge(source_id: int, target_id: int, source_db_id: int, edge_type: int):
    """Creates a directed edge between two nodes in the Rust graph."""
    payload = {
        "source_id": source_id,
        "target_id": target_id,
        "source_db_id": source_db_id,
        "edge_type": edge_type,
        "cardinality": 0,
        "is_required": 1
    }

    # Assuming your settings config maps to RUST_API or similar
    from core.config import config
    res = requests.post(f"{config.rust_engine_url}/schema/edge", json=payload)

    if res.status_code not in [200, 201]:
        print(f"❌ Rust Engine rejected the edge with HTTP {res.status_code}!")
        print(f"Raw response: {res.text}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Rust edge error: {res.text}")