import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
torch.set_num_threads(4)

from eval_harness import ModelRunner, load_eval_data, EVAL_FILE, extract_json_from_response
from config import RESULTS_DIR

def evaluate_semantic_content(raw_text: str, gt_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Relaxed / Semantic evaluation of raw model output regardless of JSON syntax.
    Evaluates domain understanding, union classification, compliance judgment,
    and violation concepts in natural language or partial JSON.
    """
    text_lower = raw_text.lower()
    gt_agreement = str(gt_json.get("agreement", "")).lower()
    gt_is_compliant = gt_json.get("is_compliant", False)
    gt_violations = gt_json.get("violations", [])
    
    # 1. Union Identification
    union_detected = False
    if gt_agreement in text_lower:
        union_detected = True
    elif gt_agreement == "bccfu" and ("iatse" in text_lower or "teamsters" in text_lower or "bccfu" in text_lower):
        union_detected = True
    elif gt_agreement == "ubcp" and ("actra" in text_lower or "ubcp" in text_lower or "performer" in text_lower):
        union_detected = True
    elif gt_agreement == "dgc" and ("directors guild" in text_lower or "dgc" in text_lower):
        union_detected = True

    # 2. Compliance Judgment
    # Look for indications of non-compliance / violation vs compliant
    indicates_violation = any(w in text_lower for w in [
        "violation", "penalty", "encroach", "exceed", "excessive", "breach", "not compliant",
        '"is_compliant": false', "is_compliant: false", "infraction", "overtime"
    ])
    indicates_compliant = any(w in text_lower for w in [
        "fully compliant", "no violation", "no infraction", '"is_compliant": true', "is_compliant: true"
    ])
    
    if not gt_is_compliant:
        compliance_judgment_correct = indicates_violation
    else:
        compliance_judgment_correct = indicates_compliant and not indicates_violation

    # 3. Violation Concepts
    # Check for specific concepts: Turnaround, Meal, Overtime
    gt_has_turnaround = any("turnaround" in v.get("violation_type", "").lower() for v in gt_violations)
    gt_has_meal = any("meal" in v.get("violation_type", "").lower() for v in gt_violations)
    gt_has_ot = any("extended" in v.get("violation_type", "").lower() or "hours" in v.get("violation_type", "").lower() for v in gt_violations)
    
    pred_has_turnaround = any(w in text_lower for w in ["turnaround", "rest period", "rest interval", "encroach", "consecutive hours off"])
    pred_has_meal = any(w in text_lower for w in ["meal", "delayed meal", "meal break", "lunch", "first meal"])
    pred_has_ot = any(w in text_lower for w in ["extended workday", "15 hours", "12 hours", "excessive hours", "double time", "overtime"])
    
    concept_hits = 0
    concept_total = 0
    if gt_has_turnaround:
        concept_total += 1
        if pred_has_turnaround: concept_hits += 1
    if gt_has_meal:
        concept_total += 1
        if pred_has_meal: concept_hits += 1
    if gt_has_ot:
        concept_total += 1
        if pred_has_ot: concept_hits += 1
        
    concept_recall = (concept_hits / concept_total) if concept_total > 0 else 1.0

    # 4. Legal / Clause Citation
    has_clause_citation = bool(re.search(r"(?:article|art\.?|section|part)\s+[A-Za-z0-9\.\-]+", text_lower))
    
    # 5. Arithmetic Hallucination Check
    # Check if model exhibits nonsensical arithmetic like summing shift + meal + rest
    has_arithmetic_hallucination = bool(re.search(r"\d+\.?\d*\s*\+\s*\d+\.?\d*\s*\+\s*\d+\.?\d*\s*=", text_lower))

    return {
        "union_detected": union_detected,
        "compliance_judgment_correct": compliance_judgment_correct,
        "concept_recall": concept_recall,
        "has_clause_citation": has_clause_citation,
        "has_arithmetic_hallucination": has_arithmetic_hallucination
    }

def run_semantic_benchmark(num_samples: int = 8):
    samples = load_eval_data(EVAL_FILE, max_samples=num_samples)
    print(f"Loaded {len(samples)} evaluation samples.")
    
    configs = [
        ("Base Model (Zero-Shot)", "base", False),
        ("Base Model + RAG", "base", True),
        ("SmolLM2-360M-Instruct", "alt", False),
        ("Fine-Tuned Model (LoRA)", "fine_tuned", False),
        ("Fine-Tuned Model + RAG", "fine_tuned", True),
    ]
    
    results = {}
    raw_logs = {}
    
    current_runner = None
    last_model_type = None
    
    for config_name, model_type, use_rag in configs:
        print(f"\n==========================================")
        print(f"Evaluating: {config_name}")
        print(f"==========================================")
        
        if model_type != last_model_type:
            current_runner = ModelRunner(model_type)
            last_model_type = model_type
            
        config_preds = []
        for idx, s in enumerate(samples):
            prompt = s["user_prompt"]
            gt = s["ground_truth_json"]
            
            resp, lat = current_runner.generate(prompt, use_rag=use_rag, max_new_tokens=150)
            parsed, is_valid_json = extract_json_from_response(resp)
            semantic = evaluate_semantic_content(resp, gt)
            
            record = {
                "sample_idx": idx,
                "prompt": prompt,
                "raw_response": resp,
                "is_valid_json": is_valid_json,
                "parsed_pred": parsed,
                "semantic": semantic,
                "latency": lat
            }
            config_preds.append(record)
            print(f"Sample {idx+1}/{len(samples)} | JSON: {is_valid_json} | Union: {semantic['union_detected']} | Compl: {semantic['compliance_judgment_correct']} | Concept Recall: {semantic['concept_recall']*100:.0f}%")
            
        # Aggregate
        total = len(config_preds)
        results[config_name] = {
            "strict_json_valid_pct": round(sum(1 for p in config_preds if p["is_valid_json"]) / total * 100, 1),
            "union_recognition_pct": round(sum(1 for p in config_preds if p["semantic"]["union_detected"]) / total * 100, 1),
            "compliance_detection_pct": round(sum(1 for p in config_preds if p["semantic"]["compliance_judgment_correct"]) / total * 100, 1),
            "violation_concept_recall_pct": round(sum(p["semantic"]["concept_recall"] for p in config_preds) / total * 100, 1),
            "clause_citation_pct": round(sum(1 for p in config_preds if p["semantic"]["has_clause_citation"]) / total * 100, 1),
            "arithmetic_hallucination_pct": round(sum(1 for p in config_preds if p["semantic"]["has_arithmetic_hallucination"]) / total * 100, 1),
            "avg_latency_s": round(sum(p["latency"] for p in config_preds) / total, 2)
        }
        raw_logs[config_name] = config_preds
        
    out_path = RESULTS_DIR / "semantic_comparison_metrics.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    log_path = RESULTS_DIR / "semantic_raw_outputs.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(raw_logs, f, indent=2)
        
    print("\n" + "=" * 80)
    print("DUAL-EVALUATION MATRIX: STRICT SYNTACTIC VS SEMANTIC DOMAIN REASONING")
    print("=" * 80)
    print(f"{'Configuration':<26} | {'Strict JSON%':<12} | {'Union Rec%':<10} | {'Compl Det%':<10} | {'Concept Rec%':<12} | {'Clause Cit%':<11} | {'Arith Error%':<12}")
    print("-" * 100)
    for name, r in results.items():
        print(f"{name:<26} | {r['strict_json_valid_pct']:<12} | {r['union_recognition_pct']:<10} | {r['compliance_detection_pct']:<10} | {r['violation_concept_recall_pct']:<12} | {r['clause_citation_pct']:<11} | {r['arithmetic_hallucination_pct']:<12}")
        
    return results

if __name__ == "__main__":
    run_semantic_benchmark(num_samples=4)
