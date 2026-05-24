use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize, Debug)]
pub struct EngineConfig {
    pub storage: StorageConfig,
    // Using String as the key is safer for TOML parsing
    pub categories: HashMap<String, String>,
}

#[derive(Deserialize, Debug)]
pub struct StorageConfig {
    pub node_limit: u64,
    pub edge_limit: u64,
    pub string_heap_mb: u64,
}