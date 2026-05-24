// src/engine/mutate.rs
use crate::engine::LichenEngine;
use crate::storage::{NodeRecord, EdgeRecord, DbHeader, RECORD_SIZE, NULL_PTR};
use zerocopy::AsBytes;

impl LichenEngine {
    pub fn add_schema_node(
        &mut self,
        label: &str,
        description: &str,
        category: u8,
        data_type: u8,
        engine_type: u8,
        source_id: u32,
        is_pk: u8,
        embedding: &Vec<f32>,
    ) -> u64 {
        let node_idx = self.next_node_idx;
        let offset = ((node_idx + 1) as usize) * RECORD_SIZE;

        // 1. Write strings to the heap, deduplicating via the intern map.
        //    If the exact string already exists on the heap, reuse its pointer
        //    instead of appending a duplicate.
        let string_heap_start = self.next_string_ptr;

        let label_bytes = label.as_bytes();
        let label_len = label_bytes.len() as u32;
        let label_ptr = if label_len > 0 {
            if let Some(&existing) = self.string_intern.get(label) {
                existing
            } else {
                let ptr = self.next_string_ptr;
                self.string_map[ptr as usize..(ptr + label_len as u64) as usize]
                    .copy_from_slice(label_bytes);
                self.next_string_ptr += label_len as u64;
                self.string_intern.insert(label.to_string(), ptr);
                ptr
            }
        } else {
            0
        };

        let desc_bytes = description.as_bytes();
        let desc_len = desc_bytes.len() as u32;
        let desc_ptr = if desc_len > 0 {
            if let Some(&existing) = self.string_intern.get(description) {
                existing
            } else {
                let ptr = self.next_string_ptr;
                self.string_map[ptr as usize..(ptr + desc_len as u64) as usize]
                    .copy_from_slice(desc_bytes);
                self.next_string_ptr += desc_len as u64;
                self.string_intern.insert(description.to_string(), ptr);
                ptr
            }
        } else {
            0
        };

        let string_heap_end = self.next_string_ptr;

        // 2. Create the 64-byte Node Record
        let node = NodeRecord {
            id: node_idx,
            first_out_edge_ptr: NULL_PTR,
            first_in_edge_ptr: NULL_PTR,
            label_ptr,
            desc_ptr,
            label_len,
            desc_len,
            source_id,
            ordinal: 0,
            category,
            data_type,
            is_pk,
            deleted: 0,
            engine_type,
            padding: [0; 5],
        };

        self.node_map[offset..offset + RECORD_SIZE].copy_from_slice(node.as_bytes());

        // 3. Write Vector Embedding (Parallel Array at 6144-byte strides)
        let vec_offset = (node_idx as usize) * 6144;
        let vec_bytes: &[u8] = embedding.as_bytes();
        self.vector_map[vec_offset..vec_offset + 6144].copy_from_slice(vec_bytes);

        // 4. Update header and in-memory state
        self.next_node_idx += 1;
        let header = unsafe { &mut *(self.node_map.as_mut_ptr() as *mut DbHeader) };
        header.node_count = self.next_node_idx;
        header.string_ptr = self.next_string_ptr;

        // 5. Update the label index so future lookups find this node in O(1)
        if label_len > 0 {
            self.node_label_index.insert((category, label.to_string()), node_idx);
        }

        // 6. Flush data to disk before the header (data → header ordering ensures
        //    the header is never ahead of the data after a crash).
        if string_heap_end > string_heap_start {
            self.string_map
                .flush_range(string_heap_start as usize, (string_heap_end - string_heap_start) as usize)
                .expect("failed to flush string data");
        }
        self.vector_map
            .flush_range(vec_offset, 6144)
            .expect("failed to flush vector data");
        self.node_map
            .flush_range(offset, RECORD_SIZE)
            .expect("failed to flush node record");
        self.node_map
            .flush_range(0, RECORD_SIZE)
            .expect("failed to flush header");

        node_idx
    }

    pub fn add_schema_edge(
        &mut self,
        from_node_id: u64,
        to_node_id: u64,
        source_db_id: u32,
        edge_type: u8,
        cardinality: u8,
        is_required: u8,
    ) -> u64 {
        let edge_idx = self.next_edge_idx;
        let offset = (edge_idx as usize) * RECORD_SIZE;

        let src_offset = ((from_node_id + 1) as usize) * RECORD_SIZE;
        let tgt_offset = ((to_node_id + 1) as usize) * RECORD_SIZE;

        // Update the Linked List pointers on the nodes
        let (old_out_head, old_in_head) = {
            let src_node = self.get_node_mut(from_node_id);
            let out_head = src_node.first_out_edge_ptr;
            src_node.first_out_edge_ptr = edge_idx;

            let tgt_node = self.get_node_mut(to_node_id);
            let in_head = tgt_node.first_in_edge_ptr;
            tgt_node.first_in_edge_ptr = edge_idx;

            (out_head, in_head)
        };

        let edge = EdgeRecord {
            source_id: from_node_id,
            target_id: to_node_id,
            next_out_ptr: old_out_head,
            next_in_ptr: old_in_head,
            weight: 1.0,
            source_db_id,
            edge_type,
            cardinality,
            is_required,
            _alignment_gap: [0; 1],
            timestamp: 0,
            padding: [0; 12],
        };

        self.edge_map[offset..offset + RECORD_SIZE].copy_from_slice(edge.as_bytes());

        self.next_edge_idx += 1;
        let header = unsafe { &mut *(self.node_map.as_mut_ptr() as *mut DbHeader) };
        header.edge_count = self.next_edge_idx;

        // Flush data before header
        self.node_map
            .flush_range(src_offset, RECORD_SIZE)
            .expect("failed to flush source node");
        self.node_map
            .flush_range(tgt_offset, RECORD_SIZE)
            .expect("failed to flush target node");
        self.edge_map
            .flush_range(offset, RECORD_SIZE)
            .expect("failed to flush edge record");
        self.node_map
            .flush_range(0, RECORD_SIZE)
            .expect("failed to flush header");

        edge_idx
    }

    fn get_node_mut(&mut self, index: u64) -> &mut NodeRecord {
        let offset = ((index + 1) as usize) * RECORD_SIZE;
        unsafe { &mut *(self.node_map.as_mut_ptr().add(offset) as *mut NodeRecord) }
    }

    pub fn update_node_description(
        &mut self,
        node_id: u64,
        new_description: &str,
    ) -> Result<(), &'static str> {
        if node_id >= self.next_node_idx {
            return Err("Node index out of bounds");
        }

        let desc_bytes = new_description.as_bytes();
        let desc_len = desc_bytes.len() as u32;

        // Reuse an existing interned string if the new description is already on the heap
        let string_heap_start = self.next_string_ptr;
        let new_desc_ptr = if desc_len > 0 {
            if let Some(&existing) = self.string_intern.get(new_description) {
                existing
            } else {
                let ptr = self.next_string_ptr;
                self.string_map[ptr as usize..(ptr + desc_len as u64) as usize]
                    .copy_from_slice(desc_bytes);
                self.next_string_ptr = ptr + desc_len as u64;
                self.string_intern.insert(new_description.to_string(), ptr);
                ptr
            }
        } else {
            0
        };
        let string_heap_end = self.next_string_ptr;

        let node_offset = ((node_id + 1) as usize) * RECORD_SIZE;
        let node = self.get_node_mut(node_id);
        node.desc_ptr = new_desc_ptr;
        node.desc_len = desc_len;

        let header = unsafe { &mut *(self.node_map.as_mut_ptr() as *mut DbHeader) };
        header.string_ptr = self.next_string_ptr;

        if string_heap_end > string_heap_start {
            self.string_map
                .flush_range(string_heap_start as usize, (string_heap_end - string_heap_start) as usize)
                .expect("failed to flush description string");
        }
        self.node_map
            .flush_range(node_offset, RECORD_SIZE)
            .expect("failed to flush node record");
        self.node_map
            .flush_range(0, RECORD_SIZE)
            .expect("failed to flush header");

        Ok(())
    }
}
