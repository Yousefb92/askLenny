use zerocopy::{AsBytes, FromBytes, FromZeroes};

#[derive(AsBytes, FromBytes, FromZeroes, Debug, Copy, Clone)]
#[repr(C)]
pub struct DbHeader {
    pub version: u32,
    pub _padding1: u32,
    pub node_count: u64,
    pub edge_count: u64,
    pub string_ptr: u64,     // Ensure this is here!
    pub _padding2: [u8; 32], // Adjusted to keep total at 64 bytes
}