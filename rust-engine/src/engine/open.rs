// src/engine/open.rs
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::path::Path;
use memmap2::MmapMut;
use crate::engine::LichenEngine;
use crate::storage::{DbHeader, NodeRecord, RECORD_SIZE};
use zerocopy::FromBytes;

impl LichenEngine {
    pub fn open<P: AsRef<Path>>(path: P, _config_path: &str) -> Result<Self, Box<dyn std::error::Error>> {
        // Define file paths
        let node_path = path.as_ref().join("nodes.dat");
        let edge_path = path.as_ref().join("edges.dat");
        let string_path = path.as_ref().join("strings.dat");
        let vector_path = path.as_ref().join("vectors.dat");

        // Hardcoded limits - lichen_config.toml is parsed but not yet wired into open()
        let max_nodes: u64 = 100_000;
        let max_edges: u64 = 500_000;
        let string_heap_size: u64 = 10 * 1024 * 1024; // 10 MB

        // 1. Create and size the files
        let node_file = OpenOptions::new().read(true).write(true).create(true).open(&node_path)?;
        node_file.set_len((max_nodes + 1) * RECORD_SIZE as u64)?;

        let edge_file = OpenOptions::new().read(true).write(true).create(true).open(&edge_path)?;
        edge_file.set_len(max_edges * RECORD_SIZE as u64)?;

        let string_file = OpenOptions::new().read(true).write(true).create(true).open(&string_path)?;
        string_file.set_len(string_heap_size)?;

        let vector_file = OpenOptions::new().read(true).write(true).create(true).open(&vector_path)?;
        vector_file.set_len((max_nodes + 1) * 6144)?;

        // 2. Map the files into virtual memory
        let mut node_map = unsafe { MmapMut::map_mut(&node_file)? };
        let edge_map = unsafe { MmapMut::map_mut(&edge_file)? };
        let string_map = unsafe { MmapMut::map_mut(&string_file)? };
        let vector_map = unsafe { MmapMut::map_mut(&vector_file)? };

        // 3. Read or Initialize the Header
        let (node_count, edge_count, string_ptr) = {
            let header = DbHeader::mut_from(&mut node_map[0..RECORD_SIZE])
                .expect("Failed to map DB Header");

            if header.version == 0 {
                header.version = 1;
                header.node_count = 0;
                header.edge_count = 0;
                header.string_ptr = 0;
                (0, 0, 0)
            } else {
                (header.node_count, header.edge_count, header.string_ptr)
            }
        };

        // 4. Rebuild in-memory indexes from existing data on disk
        let mut node_label_index: HashMap<(u8, String), u64> = HashMap::new();
        let mut string_intern: HashMap<String, u64> = HashMap::new();

        for i in 0..node_count {
            let offset = ((i + 1) as usize) * RECORD_SIZE;
            if offset + RECORD_SIZE > node_map.len() { break; }

            if let Some(record) = NodeRecord::read_from(&node_map[offset..offset + RECORD_SIZE]) {
                if record.deleted == 1 { continue; }

                if record.label_len > 0 {
                    let start = record.label_ptr as usize;
                    let end = start + record.label_len as usize;
                    if end <= string_map.len() {
                        if let Ok(label) = std::str::from_utf8(&string_map[start..end]) {
                            node_label_index.insert((record.category, label.to_string()), i);
                            string_intern.entry(label.to_string()).or_insert(record.label_ptr);
                        }
                    }
                }

                if record.desc_len > 0 {
                    let start = record.desc_ptr as usize;
                    let end = start + record.desc_len as usize;
                    if end <= string_map.len() {
                        if let Ok(desc) = std::str::from_utf8(&string_map[start..end]) {
                            string_intern.entry(desc.to_string()).or_insert(record.desc_ptr);
                        }
                    }
                }
            }
        }

        // 5. Return the initialized engine
        Ok(Self {
            node_map,
            edge_map,
            string_map,
            vector_map,
            next_node_idx: node_count,
            next_edge_idx: edge_count,
            next_string_ptr: string_ptr,
            node_label_index,
            string_intern,
        })
    }
}
