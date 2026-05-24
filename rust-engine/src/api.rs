// src/api.rs
use crate::AppState;
use crate::storage::EMBEDDING_DIMS;
use axum::{
    extract::{State, Json},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

// ---------------------------------------------------------
// 1. SYSTEM
// ---------------------------------------------------------
pub async fn health_check() -> &'static str {
    "LichenEngine AI Graph Database 1.1 is active."
}

// ---------------------------------------------------------
// 2. MUTATIONS (Requires Write Lock)
// ---------------------------------------------------------
#[derive(Deserialize)]
pub struct AddNodeReq {
    pub label: String,
    pub description: String,
    pub category: u8,
    pub data_type: u8,
    pub engine_type: u8,
    pub source_id: u32,
    pub is_pk: u8,
    pub embedding: Vec<f32>
}

#[derive(Serialize)]
pub struct AddNodeRes {
    pub node_id: u64,
}

pub async fn add_node(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<AddNodeReq>,
) -> Response {
    if payload.embedding.len() != EMBEDDING_DIMS {
        return (
            StatusCode::BAD_REQUEST,
            format!("embedding must be exactly {} floats, got {}", EMBEDDING_DIMS, payload.embedding.len()),
        ).into_response();
    }

    let mut db = state.db.write().await;

    let node_id = db.add_schema_node(
        &payload.label,
        &payload.description,
        payload.category,
        payload.data_type,
        payload.engine_type,
        payload.source_id,
        payload.is_pk,
        &payload.embedding,
    );

    (StatusCode::CREATED, Json(AddNodeRes { node_id })).into_response()
}

#[derive(Deserialize)]
pub struct AddEdgeReq {
    pub source_id: u64,
    pub target_id: u64,
    pub source_db_id: u32,
    pub edge_type: u8,
    pub cardinality: u8,
    pub is_required: u8,
}

pub async fn add_edge(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<AddEdgeReq>,
) -> impl IntoResponse {
    let mut db = state.db.write().await;

    db.add_schema_edge(
        payload.source_id,
        payload.target_id,
        payload.source_db_id,
        payload.edge_type,
        payload.cardinality,
        payload.is_required,
    );

    StatusCode::CREATED
}

// ---------------------------------------------------------
// 3. QUERIES (Requires Read Lock)
// ---------------------------------------------------------
#[derive(Deserialize)]
pub struct VectorSearchReq {
    pub query_embedding: Vec<f32>,
    pub limit: usize,
    pub source_id: u32
}

#[derive(Serialize)]
pub struct VectorSearchRes {
    pub matched_node_ids: Vec<u64>,
    pub graphrag_context: String
}

pub async fn list_nodes(
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    let db = state.db.read().await;
    let nodes = db.list_all_nodes();
    (StatusCode::OK, Json(nodes))
}

pub async fn list_edges(
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    let db = state.db.read().await;
    let edges = db.list_all_edges();
    (StatusCode::OK, Json(edges))
}

pub async fn vector_search(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<VectorSearchReq>,
) -> impl IntoResponse {
    let db = state.db.read().await;

    // Find the closest matching nodes by cosine similarity
    let matched_nodes = db.cosine_similarity_search(&payload.query_embedding, payload.limit, payload.source_id);

    // Walk each match one level deep and concatenate the GraphRAG context blocks
    let mut complete_context = String::new();
    for &node_id in &matched_nodes {
        let node_context = db.extract_graphrag_context(node_id, 1);
        complete_context.push_str(&node_context);
        complete_context.push_str("\n---\n");
    }

    // Return matched IDs and the assembled context in a single response
    (StatusCode::OK, Json(VectorSearchRes {
        matched_node_ids: matched_nodes,
        graphrag_context: complete_context
    }))
}

#[derive(Deserialize)]
pub struct ContextReq {
    pub starting_node_id: u64,
    pub max_depth: u8,
}

#[derive(Serialize)]
pub struct ContextRes {
    pub markdown_prompt: String,
}

pub async fn get_ai_context(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<ContextReq>,
) -> impl IntoResponse {
    let db = state.db.read().await;

    let prompt = db.extract_graphrag_context(payload.starting_node_id, payload.max_depth);

    (StatusCode::OK, Json(ContextRes { markdown_prompt: prompt }))
}

// Checks whether a node with the given label and category exists in the graph.
#[derive(Deserialize)]
pub struct NodeLookupReq {
    pub label: String,
    pub category: u8, // 0 = DB, 1 = Table, 2 = Column
}

#[derive(Serialize)]
pub struct NodeLookupRes {
    pub exists: bool,
    pub node_id: Option<u64>, // Returns null in JSON if exists is false
}

pub async fn lookup_node(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<NodeLookupReq>,
) -> impl IntoResponse {
    let db = state.db.read().await;

    match db.find_node_idx_by_label(&payload.label, payload.category) {
        Some(node_id) => {
            (StatusCode::OK, Json(NodeLookupRes { exists: true, node_id: Some(node_id) }))
        }
        None => {
            (StatusCode::OK, Json(NodeLookupRes { exists: false, node_id: None }))
        }
    }
}

// Updates the plain-English description for an existing node.
#[derive(Deserialize)]
pub struct UpdateDescReq {
    pub node_id: u64,
    pub description: String,
}

pub async fn update_description(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<UpdateDescReq>,
) -> impl IntoResponse {
    let mut db = state.db.write().await;

    match db.update_node_description(payload.node_id, &payload.description) {
        Ok(_) => StatusCode::OK.into_response(),
        Err(e) => (StatusCode::BAD_REQUEST, e).into_response(),
    }
}