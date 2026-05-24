// src/engine/query.rs
use crate::engine::LichenEngine;
use crate::storage::{NodeRecord, RECORD_SIZE, EdgeRecord, EDGE_RECORD_SIZE, NULL_PTR};
use serde::Serialize;
use zerocopy::FromBytes;
use std::collections::{HashSet, VecDeque};

// This is the "Lightweight" version of a node we send to Python
#[derive(Serialize)]
pub struct NodeSummary {
    pub id: u64,
    pub label: String,
    pub description: String,
    pub category: u8,
    pub data_type: u8,
    pub source_id: u32
}

// Lightweight edge summary returned by list_all_edges
#[derive(Serialize)]
pub struct EdgeSummary {
    pub from_node_id: u64,
    pub to_node_id: u64,
    pub edge_type: u8,
    pub source_db_id: u32,
}

impl LichenEngine {
    /// Returns every active node in the graph.
    /// Used by the Python Orchestrator to calculate deltas.
    pub fn list_all_nodes(&self) -> Vec<NodeSummary> {
        let mut nodes = Vec::new();

        // Loop from 0 to next_node_idx.
        // Note: Offset starts at 1 * RECORD_SIZE because index 0 is the Header.
        for i in 0..self.next_node_idx {
            let offset = ((i + 1) as usize) * RECORD_SIZE;

            // Get the 64-byte slice from the memory map
            let bytes = &self.node_map[offset..offset + RECORD_SIZE];

            // Convert those binary bytes into a Rust struct we can read
            if let Some(record) = NodeRecord::read_from(bytes) {
                // Ignore nodes that have been "deleted"
                if record.deleted == 0 {
                    nodes.push(NodeSummary {
                        id: record.id,
                        label: self.get_string(record.label_ptr, record.label_len),
                        description: self.get_string(record.desc_ptr, record.desc_len),
                        category: record.category,
                        data_type: record.data_type,
                        source_id: record.source_id,
                    });
                }
            }
        }
        nodes
    }

    pub fn get_string(&self, ptr: u64, len: u32) -> String {
        if len == 0 { return "".to_string(); }
        let start = ptr as usize;
        let end = (ptr + len as u64) as usize;
        let bytes = &self.string_map[start..end];
        String::from_utf8_lossy(bytes).to_string()
    }

    pub fn cosine_similarity_search(&self, query_embedding: &Vec<f32>, limit: usize, target_source_id: u32) -> Vec<u64> {
        if query_embedding.is_empty() {
            return Vec::new();
        }

        let query_mag: f32 = query_embedding.iter().map(|&x| x * x).sum::<f32>().sqrt();
        if query_mag == 0.0 {
            return Vec::new();
        }

        let mut scored_nodes: Vec<(u64, f32)> = Vec::new();

        // Each vector has 1536 floats. 1 float = 4 bytes.
        // Total byte size per vector record = 6144 bytes.
        let float_count = 1536;
        let vector_stride = float_count * 4;

        for i in 0..self.next_node_idx {
            let offset = ((i + 1) as usize) * RECORD_SIZE;
            if offset + RECORD_SIZE > self.node_map.len() { break; }

            let bytes = &self.node_map[offset..offset + RECORD_SIZE];

            if let Some(record) = NodeRecord::read_from(bytes) {
                if record.deleted == 1 { continue; }
                if record.source_id != target_source_id { continue; }

                // --- FIX: Safely slice and cast the raw byte map into an f32 slice ---
                let start_byte = (record.id as usize) * vector_stride;
                let end_byte = start_byte + vector_stride;
                if end_byte > self.vector_map.len() { continue; }

                let raw_vector_bytes = &self.vector_map[start_byte..end_byte];

                // Zero-copy pointer cast from byte slice to f32 slice
                let node_embedding: &[f32] = unsafe {
                    std::slice::from_raw_parts(raw_vector_bytes.as_ptr() as *const f32, float_count)
                };

                // 1. Calculate Dot Product
                let dot_product: f32 = query_embedding.iter()
                    .zip(node_embedding.iter())
                    .map(|(&q, &n)| q * n)
                    .sum();

                // 2. Calculate Node Vector Magnitude
                let node_mag: f32 = node_embedding.iter().map(|&x| x * x).sum::<f32>().sqrt();

                // 3. Compute Score
                let score = if node_mag > 0.0 {
                    dot_product / (query_mag * node_mag)
                } else {
                    0.0
                };

                scored_nodes.push((record.id, score));
            }
        }

        // Drop any non-finite scores (NaN or ±inf) before sorting so that the
        // sort comparator always receives a total order.
        scored_nodes.retain(|(_, s)| s.is_finite());
        scored_nodes.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        scored_nodes.into_iter()
            .take(limit)
            .map(|(node_id, _score)| node_id)
            .collect()
    }
    pub fn extract_graphrag_context(&self, starting_node_id: u64, max_depth: u8) -> String {
        let mut context = String::new();

        let offset = ((starting_node_id + 1) as usize) * RECORD_SIZE;
        if offset + RECORD_SIZE > self.node_map.len() {
            return "Node not found\n".to_string();
        }

        let bytes = &self.node_map[offset..offset + RECORD_SIZE];
        let start_record = match NodeRecord::read_from(bytes) {
            Some(record) => record,
            None => return "Node not found\n".to_string(),
        };

        if start_record.deleted == 1 {
            return "Node has been deleted\n".to_string();
        }

        let start_label = self.get_string(start_record.label_ptr, start_record.label_len);

        let mut queue = VecDeque::new();
        let mut visited = HashSet::new();

        queue.push_back((starting_node_id, 0));
        visited.insert(starting_node_id);

        context.push_str(&format!("--- Anchor Context for [{}] ---\n", start_label));

        while let Some((current_id, depth)) = queue.pop_front() {
            let current_offset = ((current_id + 1) as usize) * RECORD_SIZE;
            if current_offset + RECORD_SIZE > self.node_map.len() { continue; }

            let current_bytes = &self.node_map[current_offset..current_offset + RECORD_SIZE];

            if let Some(node) = NodeRecord::read_from(current_bytes) {
                if node.deleted == 1 { continue; }

                let label = self.get_string(node.label_ptr, node.label_len);
                let description = self.get_string(node.desc_ptr, node.desc_len);

                // 1. Resolve Category Strings
                let cat_str = match node.category {
                    0 => "Database",
                    1 => "Table",
                    2 => "Column",
                    _ => "Unknown",
                };

                // 2. NEW: Decode binary Data Type integer to explicit SQL type names
                let type_str = match node.data_type {
                    1 => "INT/INTEGER",
                    2 => "VARCHAR/NVARCHAR",
                    3 => "DATETIME/TIMESTAMP",
                    4 => "DECIMAL/FLOAT",
                    5 => "BOOLEAN/BIT",
                    _ => "UNKNOWN_TYPE",
                };

                // 3. NEW: Decode binary Engine Type integer to explicit Dialect definitions
                let engine_str = match node.engine_type {
                    1 => "Microsoft SQL Server (T-SQL/SQLExpress)",
                    2 => "PostgreSQL (PL/pgSQL)",
                    3 => "MySQL",
                    4 => "Snowflake",
                    _ => "Standard ANSI SQL",
                };

                // 4. NEW: Pull your Primary Key flag into context
                let pk_suffix = if node.is_pk == 1 { " [PRIMARY KEY]" } else { "" };

                // 5. Build tailored text blocks based on node category
                if node.category == 2 {
                    // Columns need to show Data Type constraints
                    context.push_str(&format!(
                        "[{}] (ID: {}, Depth: {}){}\nLabel: {}\nData Type: {}\nDescription: {}\n\n",
                        cat_str, current_id, depth, pk_suffix, label, type_str, description
                    ));
                } else {
                    // Databases and Tables dictate the Engine dialect layout
                    context.push_str(&format!(
                        "[{}] (ID: {}, Depth: {})\nLabel: {}\nEngine Dialect: {}\nDescription: {}\n\n",
                        cat_str, current_id, depth, label, engine_str, description
                    ));
                }

                // Follow the linked list of outgoing edges from this node
                if depth < max_depth {
                    let mut edge_idx = node.first_out_edge_ptr;
                    while edge_idx != NULL_PTR {
                        let e_offset = edge_idx as usize * EDGE_RECORD_SIZE;
                        if e_offset + EDGE_RECORD_SIZE > self.edge_map.len() { break; }
                        if let Some(edge) = EdgeRecord::read_from(&self.edge_map[e_offset..e_offset + EDGE_RECORD_SIZE]) {
                            if !visited.contains(&edge.target_id) {
                                visited.insert(edge.target_id);
                                queue.push_back((edge.target_id, depth + 1));
                            }
                            edge_idx = edge.next_out_ptr;
                        } else {
                            break;
                        }
                    }
                }
            }
        }

        context
    }

    /// Returns every edge in the graph.
    /// Used by the Python orchestrator to restore FK state on discovery reload
    /// and to deduplicate FK edges on repeated commits.
    pub fn list_all_edges(&self) -> Vec<EdgeSummary> {
        let mut edges = Vec::new();
        for i in 0..self.next_edge_idx {
            let offset = i as usize * EDGE_RECORD_SIZE;
            if offset + EDGE_RECORD_SIZE > self.edge_map.len() { break; }
            if let Some(record) = EdgeRecord::read_from(&self.edge_map[offset..offset + EDGE_RECORD_SIZE]) {
                edges.push(EdgeSummary {
                    from_node_id: record.source_id,
                    to_node_id:   record.target_id,
                    edge_type:    record.edge_type,
                    source_db_id: record.source_db_id,
                });
            }
        }
        edges
    }

    pub fn find_node_idx_by_label(&self, target_label: &str, target_category: u8) -> Option<u64> {
        // O(1) HashMap lookup using the in-memory label index rebuilt on boot.
        self.node_label_index
            .get(&(target_category, target_label.to_string()))
            .copied()
    }
}