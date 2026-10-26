import os
import sys
import json
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from build_vectorstore import query_knowledge_base
from rag_pipeline import build_compliance_graph

class TestBCFilmLabourSystem(unittest.TestCase):
    def test_01_vectorstore_retrieval(self):
        """Test that ChromaDB returns accurate collective agreement clauses."""
        query = "DGC BC Third Assistant Director rest turnaround"
        results = query_knowledge_base(query, n_results=2)
        self.assertGreater(len(results), 0)
        found_clauses = [r["clause"] for r in results]
        # Should retrieve DGC Article 17.1
        self.assertTrue(any("DGC" in c for c in found_clauses), f"Expected DGC clause, got {found_clauses}")

    def test_02_model_checkpoint_exists(self):
        """Verify fine-tuned LoRA weights and configs exist."""
        adapter_file = config.OUTPUT_DIR / "adapter_model.safetensors"
        config_file = config.OUTPUT_DIR / "adapter_config.json"
        history_file = config.OUTPUT_DIR / "training_history.json"
        
        self.assertTrue(adapter_file.exists(), f"Missing {adapter_file}")
        self.assertTrue(config_file.exists(), f"Missing {config_file}")
        self.assertTrue(history_file.exists(), f"Missing {history_file}")

    def test_03_rag_pipeline_execution(self):
        """Test LangGraph StateGraph execution with mock/callable model."""
        sample_audit_json = {
            "agreement": "BCCFU",
            "classification": "Dolly Operator",
            "is_compliant": False,
            "violations": [
                {
                    "violation_type": "Turnaround Encroachment",
                    "clause": "BCCFU Article A1.20(a)",
                    "description": "Rest period of 7.0h fails to meet 10.0h.",
                    "hours_affected": 3.0
                }
            ]
        }
        
        def mock_llm(prompt):
            return f"```json\n{json.dumps(sample_audit_json, indent=2)}\n```"

        app = build_compliance_graph(mock_llm)
        initial_state = {
            "query": "Role: Dolly Operator under BCCFU\nShift: 10h\nMeal: 5h\nRest: 7h",
            "use_rag": True,
            "retrieved_clauses": [],
            "prompt": "",
            "model_name_or_path": "mock",
            "raw_output": "",
            "parsed_report": None,
            "is_valid_json": False,
            "error": None
        }
        
        final_state = app.invoke(initial_state)
        self.assertTrue(final_state["is_valid_json"])
        self.assertEqual(final_state["parsed_report"]["agreement"], "BCCFU")
        self.assertEqual(len(final_state["parsed_report"]["violations"]), 1)
        self.assertGreater(len(final_state["retrieved_clauses"]), 0)

if __name__ == "__main__":
    unittest.main()
