// Bulk CSV ingestion - not currently wired up.
// References EngineIndex and add_node/add_edge signatures that no longer match the engine API.
// Kept as a reference for a future bulk-load path.
use crate::engine::{LichenEngine, EngineIndex};
use std::error::Error;
use csv::Reader;

pub fn load_from_csv(
    db: &mut LichenEngine,
    index: &mut EngineIndex,
    file_path: &str
) -> Result<(), Box<dyn Error>> {
    let mut reader = Reader::from_path(file_path)?;

    println!("Starting ingestion from {}...", file_path);

    for result in reader.records() {
        let record = result?;
        let entry_type = &record[0]; // "node" or "edge"

        match entry_type {
            "node" => {
                // Only parse the columns used by nodes
                let id: u64 = record.get(1).ok_or("Missing ID")?.parse()?;
                let label = record.get(2).unwrap_or("");
                let category: u8 = record.get(3).ok_or("Missing Category")?.parse()?;

                if !index.all_nodes.contains_key(&id) {
                    let internal_idx = db.add_node(id, category, label);
                    index.all_nodes.insert(id, internal_idx);

                    // Update buckets for Phase 3 queries
                    match category {
                        1 => index.customers.push(internal_idx),
                        3 => index.products.push(internal_idx),
                        _ => {}
                    }
                }
            }
            "edge" => {
                // Edges use different columns: source_id (1), target_id (4), weight (5)
                // Based on the Python script's output format
                let source_id: u64 = record.get(1).ok_or("Missing Source ID")?.parse()?;
                let target_id: u64 = record.get(4).ok_or("Missing Target ID")?.parse()?;
                let weight: f32 = record.get(5).ok_or("Missing Weight")?.parse()?;

                if let (Some(&src), Some(&tgt)) = (
                    index.all_nodes.get(&source_id),
                    index.all_nodes.get(&target_id)
                ) {
                    db.add_edge(src, tgt, weight);
                }
            }
            _ => continue,
        }
    }
    Ok(())
}