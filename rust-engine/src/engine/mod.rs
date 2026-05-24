// src/engine/mod.rs
pub mod open;
pub mod mutate;
pub mod query;

use memmap2::MmapMut;
use std::collections::HashMap;

pub struct LichenEngine {
    // The Core Memory Maps
    pub node_map: MmapMut,
    pub edge_map: MmapMut,
    pub string_map: MmapMut,
    pub vector_map: MmapMut,

    // Volatile State (Hydrated on boot)
    pub next_node_idx: u64,
    pub next_edge_idx: u64,
    pub next_string_ptr: u64,

    // In-memory indexes (rebuilt from disk on boot)
    // Maps (category, label) → node_idx for O(1) duplicate detection during ingestion
    pub(crate) node_label_index: HashMap<(u8, String), u64>,
    // Maps string content → heap offset to avoid writing duplicate strings
    pub(crate) string_intern: HashMap<String, u64>,
}