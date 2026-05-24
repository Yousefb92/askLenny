from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from pydantic import BaseModel
from processor import generate_multi_db_proposal
import os
import requests
from services.ai_service import AIDescriptionService
from services.sync_service import GraphSyncService
from services.query_service import QueryService

# Run locally using
# uvicorn main:app --reload --port 8000
load_dotenv()
app = FastAPI(title="Lichen Orchestrator")

# --- 1. CORS Configuration (Crucial for Frontend) ---
# When your frontend (e.g., localhost:5173) tries to talk to this API (localhost:8000),
# the browser will block it unless CORS is enabled.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EnrichRequest(BaseModel):
    db_name: str
    table_name: str
    column_name: Optional[str] = None
    data_type: Optional[str] = None
    table_columns: Optional[List[str]] = None


class ColumnSpec(BaseModel):
    name: str
    data_type: Optional[str] = None


class BatchEnrichRequest(BaseModel):
    db_name: str
    table_name: str
    table_description: str = ""
    columns: List[ColumnSpec]   # only the columns that need descriptions


# The On-Demand AI Endpoint
@app.post("/sync/enrich")
async def generate_ai_description(req: EnrichRequest):
    try:
        # Delegate the work to the service layer
        ai_text = AIDescriptionService.generate_description(
            db_name=req.db_name,
            table_name=req.table_name,
            column_name=req.column_name,
            data_type=req.data_type,
            table_columns=req.table_columns
        )
        return {"status": "success", "description": ai_text}

    except Exception as e:
        print(f"Gemini AI Generation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 1b. Batch column enrichment (single LLM call for a whole table) ---
@app.post("/sync/enrich_table")
async def batch_enrich_table(req: BatchEnrichRequest):
    try:
        descriptions = AIDescriptionService.generate_batch_column_descriptions(
            db_name=req.db_name,
            table_name=req.table_name,
            table_description=req.table_description,
            columns=[{"name": c.name, "data_type": c.data_type} for c in req.columns],
        )
        return {"status": "success", "descriptions": descriptions}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"Batch Enrich Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- 2. The Discovery Endpoint (Read-Only) ---
@app.get("/sync/gapdiscovery")
async def gap_discovery():
    """
    Scans the SQL Databases defined in the YAML, compares them to the Rust DB,
    and returns a nested JSON proposal of what is 'New' or 'Synchronized'.
    """
    try:
        print("API Request: Generating Sync Proposals...")
        proposal_report = generate_multi_db_proposal()
        return {"status": "success", "data": proposal_report}
    except Exception as e:
        print(f"API Error during proposal generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 3. The Commit Endpoint (Write) ---
@app.post("/sync/commit")
async def commit_to_graph(payload: dict = Body(...)):
    try:
        print("Starting hierarchical commit to Rust...")

        # Instantiate the service and let it handle the heavy lifting
        sync_service = GraphSyncService()
        result = sync_service.process_payload(payload)

        return result

    except Exception as e:
        print(f"Commit Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────
# QUERY ENGINE ENDPOINTS
# ─────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    db_name: str
    limit: int = 5   # number of graph nodes to retrieve from vector search


class ExecuteRequest(BaseModel):
    sql: str
    db_name: str


# --- 5. Natural-language → SQL + auto-execute ---
@app.post("/query/ask")
async def ask_query(req: AskRequest):
    """
    Full RAG-to-SQL pipeline:
      1. Embed the question
      2. Vector search the Rust graph for relevant schema nodes
      3. Generate dialect-accurate SQL via Gemini
      4. Execute the SQL against the source database
      5. Return both the SQL and the result set

    Response shape:
      { status, sql, columns, rows, row_count }
    """
    try:
        service = QueryService()
        result = service.ask(
            question=req.question,
            db_name=req.db_name,
            limit=req.limit,
        )
        return {"status": "success", **result}

    except ValueError as e:
        # Configuration / context errors — bad request, not server fault
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[/query/ask] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- 6. Re-execute a pre-generated SQL statement ---
@app.post("/query/execute")
async def execute_query(req: ExecuteRequest):
    """
    Runs a raw SQL string against the named database and returns the result set.
    Used when the user wants to re-run a previously generated query.

    Response shape:
      { status, columns, rows, row_count }
    """
    try:
        service = QueryService()
        result = service.execute(sql=req.sql, db_name=req.db_name)
        return {"status": "success", **result}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[/query/execute] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- 7. Health Check ---
@app.get("/health")
def health():
    return {"status": "Orchestrator Online"}

