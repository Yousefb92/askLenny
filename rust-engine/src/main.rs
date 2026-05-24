// src/main.rs
mod api;
mod config;
mod engine;
mod storage;

use axum::Router;
use engine::LichenEngine;
use std::fs;
use std::sync::Arc;
use axum::routing::get;
use tokio::sync::RwLock;
use crate::api::{health_check, add_node, add_edge, list_nodes, list_edges};

// This holds our application state.
// Arc allows multiple threads to share ownership.
// RwLock allows multiple concurrent readers (for querying) but exclusive access for writers (adding tables).
pub struct AppState {
    pub db: Arc<RwLock<LichenEngine>>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let db_path = "./lichen_persistent";
    let config_path = "lichen_config.toml";

    // Ensure the data directory exists
    fs::create_dir_all(db_path)?;

    println!("Booting LichenEngine...");

    // 1. Initialize the Memory-Mapped Engine (We will build this in engine/open.rs)
    let engine = LichenEngine::open(db_path, config_path)?;
    println!("Engine booted. Nodes: {}, Edges: {}", engine.next_node_idx, engine.next_edge_idx);

    // 2. Wrap the engine in our thread-safe AppState
    let shared_state = Arc::new(AppState {
        db: Arc::new(RwLock::new(engine)),
    });

    // 3. Define the API Routes
    let app = Router::new()
        // --- System ---
        .route("/health", axum::routing::get(api::health_check))

        // --- Write Endpoints (Mutations) ---
        .route("/schema/node", axum::routing::post(api::add_node))
        .route("/schema/edge", axum::routing::post(api::add_edge))

        // --- Read Endpoints (AI Queries) ---
        .route("/query/vector_search", axum::routing::post(api::vector_search))
        .route("/query/context", axum::routing::post(api::get_ai_context))

        // Getting current Schema definition and mapping - run each time app boots
        .route("/schema/nodes", axum::routing::get(api::list_nodes))
        .route("/schema/edges", axum::routing::get(api::list_edges))
        // Attach the database state to all routes

        //     lookup function to check if DB node exists
        .route("/schema/node/lookup", axum::routing::post(api::lookup_node))
        // Node description mutation
        .route("/node/updateDescription", axum::routing::post(api::update_description))
        .with_state(shared_state);



    // 4. Start the Server
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await?;
    println!("LichenGraph API running continuously on http://0.0.0.0:3000");
    axum::serve(listener, app).await?;

    Ok(())
}