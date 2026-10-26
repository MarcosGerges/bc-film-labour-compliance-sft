import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from langgraph.graph import StateGraph, END
from config import SYSTEM_PROMPT
from build_vectorstore import query_knowledge_base

class AuditState(dict):
    """LangGraph state schema for BC Film Labour Compliance Audit."""
    query: str
    use_rag: bool
    retrieved_clauses: List[Dict[str, Any]]
    prompt: str
    model_name_or_path: str
    raw_output: str
    parsed_report: Optional[Dict[str, Any]]
    is_valid_json: bool
    error: Optional[str]

def retrieve_node(state: AuditState) -> Dict[str, Any]:
    """Retrieve relevant collective agreement clauses if RAG is enabled."""
    if not state.get("use_rag", False):
        return {"retrieved_clauses": []}
    
    query = state["query"]
    retrieved = query_knowledge_base(query, n_results=2)
    return {"retrieved_clauses": retrieved}

def format_prompt_node(state: AuditState) -> Dict[str, Any]:
    """Format prompt with system instructions, user query, and optional retrieved clauses."""
    clauses = state.get("retrieved_clauses", [])
    query = state["query"]
    
    if clauses and state.get("use_rag", False):
        context_str = "\n\nRelevant BC Collective Agreement Clauses Grounding:\n"
        for c in clauses:
            context_str += f"- [{c.get('clause')}]: {c.get('content')}\n"
        augmented_query = f"{query}\n{context_str}\nAudit strictly using these cited collective agreements."
    else:
        augmented_query = query
        
    return {"prompt": augmented_query}

def generate_node_stub(state: AuditState, model_engine=None) -> Dict[str, Any]:
    """Node that invokes the model engine (injected or default)."""
    # This node is dynamically replaced or executed by the compliance runner
    prompt = state["prompt"]
    if model_engine is not None:
        raw_output = model_engine(prompt)
    else:
        raw_output = state.get("raw_output", "")
    return {"raw_output": raw_output}

def parse_and_validate_node(state: AuditState) -> Dict[str, Any]:
    """Extract and validate JSON compliance audit report."""
    raw = state.get("raw_output", "")
    report = None
    is_valid = False
    error = None
    
    try:
        # Extract markdown json if present
        if "```json" in raw:
            json_text = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            json_text = raw.split("```")[1].split("```")[0].strip()
        else:
            json_text = raw.strip()
            
        data = json.loads(json_text)
        
        # Verify required keys
        required_keys = ["agreement", "classification", "is_compliant", "violations"]
        if all(k in data for k in required_keys):
            report = data
            is_valid = True
        else:
            error = f"Missing required keys: {[k for k in required_keys if k not in data]}"
    except Exception as e:
        error = f"JSON decode failed: {str(e)}"
        
    return {
        "parsed_report": report,
        "is_valid_json": is_valid,
        "error": error
    }

def build_compliance_graph(model_callable):
    """Constructs a LangGraph StateGraph pipeline for the audit workflow."""
    workflow = StateGraph(AuditState)
    
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("format_prompt", format_prompt_node)
    workflow.add_node("generate", lambda state: generate_node_stub(state, model_callable))
    workflow.add_node("parse_validate", parse_and_validate_node)
    
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "format_prompt")
    workflow.add_edge("format_prompt", "generate")
    workflow.add_edge("generate", "parse_validate")
    workflow.add_edge("parse_validate", END)
    
    return workflow.compile()
