// src/storage/node.rs
use zerocopy::{AsBytes, FromBytes, FromZeroes};

#[derive(AsBytes, FromBytes, FromZeroes, Debug, Copy, Clone)]
#[repr(C)]
pub struct NodeRecord {
    // --- 8-Byte Fields (40 bytes total) ---
    pub id: u64,
    pub first_out_edge_ptr: u64,
    pub first_in_edge_ptr: u64,
    pub label_ptr: u64,
    pub desc_ptr: u64,            // Moved up to maintain 8-byte alignment!

    // --- 4-Byte Fields (8 bytes total) ---
    pub label_len: u32,
    pub desc_len: u32,
    pub source_id: u32, // The owning db name

    // --- 2-Byte Fields (2 bytes total) ---
    pub ordinal: u16,

    // --- 1-Byte Fields (5 bytes total) ---
    pub category: u8, // 0 for db, 1 for table, 2 for column
    pub data_type: u8,
    pub is_pk: u8,
    pub deleted: u8,
    pub engine_type: u8,

    // --- Explicit Padding (5 bytes total) ---
    // 40 + 12 + 2 + 5 = 59 bytes used.
    // 64 - 59 = 5 bytes of padding needed to reach 64.
    pub padding: [u8; 5],
}