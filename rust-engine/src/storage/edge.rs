// src/storage/edge.rs
use zerocopy::{AsBytes, FromBytes, FromZeroes};

#[derive(AsBytes, FromBytes, FromZeroes, Debug, Copy, Clone)]
#[repr(C)]
pub struct EdgeRecord {
    pub source_id: u64,         // 8 bytes (e.g., Node 'user_id')
    pub target_id: u64,         // 8 bytes (e.g., Node 'id' in Users table)
    pub next_out_ptr: u64,      // 8 bytes
    pub next_in_ptr: u64,       // 8 bytes
    pub timestamp: u64,         // 8 bytes

    // AI Traversal Metrics
    pub weight: f32,            // 4 bytes (Used for Vector Similarity/Relevance scoring)
    pub source_db_id: u32,

    // AI Schema Metadata
    pub edge_type: u8,          // 1 byte  (0 = Contains/Nested, 1 = Foreign Key/Link)
    pub cardinality: u8,        // 1 byte  (NEW: 0=Unknown, 1=OneToOne, 2=OneToMany, 3=ManyToMany)
    pub is_required: u8,        // 1 byte  (NEW: 0=Nullable/Left Join, 1=Required/Inner Join)

    pub _alignment_gap: [u8; 1], // 1 byte  (Total so far: 32 + 4 + 1 + 1 + 1 + 1 = 40 bytes)


    pub padding: [u8; 12],      // 16 bytes (Total = 64 bytes)
}