// src/storage/mod.rs

pub mod node;    // Links src/storage/node.rs
pub mod edge;    // Links src/storage/edge.rs
pub mod header;  // Links src/storage/header.rs

// Re-export so others can use storage::NodeRecord
pub use node::NodeRecord;
pub use edge::EdgeRecord;
pub use header::DbHeader;

pub const RECORD_SIZE: usize = 64;
pub const EDGE_RECORD_SIZE: usize = 64;
pub const NULL_PTR: u64 = u64::MAX;
pub const EMBEDDING_DIMS: usize = 1536;