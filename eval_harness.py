import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Add script directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Force offline mode so huggingface loads exclusively from local cache
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import torch
torch.set_num_threads(4)

from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from config import (
    BASE_MODEL_NAME,
    ALT_MODEL_NAME,
    OUTPUT_DIR,
    EVAL_FILE,
    RESULTS_DIR,
    SYSTEM_PROMPT
)
from build_vectorstore import query_knowledge_base

def extract_json_from_response(raw_text: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Parse JSON from model response text, handling markdown fences and formatting."""
    try:
        if "```json" in raw_text:
            cleaned = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            cleaned = raw_text.split("```")[1].split("```")[0].strip()
        else:
            cleaned = raw_text.strip()
            
        data = json.loads(cleaned)
        required_keys = ["agreement", "classification", "is_compliant", "violations"]
        if all(k in data for k in required_keys):
            return data, True
        return data, False
    except Exception:
        try:
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = raw_text[start:end+1]
                data = json.loads(candidate)
                required_keys = ["agreement", "classification", "is_compliant", "violations"]
                if all(k in data for k in required_keys):
                    return data, True
                return data, False
        except Exception:
            pass
        return None, False

def load_eval_data(file_path: Path, max_samples: int = None):
    """Load evaluation test set from eval.jsonl."""
    samples = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                user_content = entry["messages"][1]["content"]
                asst_content = entry["messages"][2]["content"]
                gt_json, _ = extract_json_from_response(asst_content)
                samples.append({
                    "user_prompt": user_content,
                    "ground_truth_raw": asst_content,
                    "ground_truth_json": gt_json
                })
                if max_samples and len(samples) >= max_samples:
                    break
    return samples

class ModelRunner:
    """Wrapper to handle inference for Base, Fine-Tuned, and Alternative models."""
    def __init__(self, model_type: str, device: str = "cpu"):
        self.model_type = model_type
        self.device = device
        print(f"Initializing ModelRunner: {model_type} on {device}...", flush=True)
        
        dtype = torch.float32
        
        if model_type == "fine_tuned":
            print(f"Loading Base model ({BASE_MODEL_NAME}) and LoRA adapter ({OUTPUT_DIR})...", flush=True)
            self.tokenizer = AutoTokenizer.from_pretrained(str(OUTPUT_DIR), use_fast=True, local_files_only=True)
            base_model = AutoModelForCausalLM.from_pretrained(
                BASE_MODEL_NAME,
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
                local_files_only=True
            )
            self.model = PeftModel.from_pretrained(base_model, str(OUTPUT_DIR))
            self.model.eval()
            
        elif model_type == "base":
            print(f"Loading Zero-Shot Base model ({BASE_MODEL_NAME})...", flush=True)
            self.tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_NAME, use_fast=True, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                BASE_MODEL_NAME,
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
                local_files_only=True
            )
            self.model.eval()
            
        elif model_type == "alt":
            print(f"Loading Open-Source Alternative model ({ALT_MODEL_NAME})...", flush=True)
            self.tokenizer = AutoTokenizer.from_pretrained(ALT_MODEL_NAME, use_fast=True, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                ALT_MODEL_NAME,
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
                local_files_only=True
            )
            self.model.eval()
        else:
            raise ValueError(f"Unknown model_type: {model_type}")

    def generate(self, user_prompt: str, use_rag: bool = False, max_new_tokens: int = 140) -> Tuple[str, float]:
        """Generate response given user prompt with optional RAG augmentation."""
        if use_rag:
            clauses = query_knowledge_base(user_prompt, n_results=2)
            rag_context = "\n\nRelevant BC Film Collective Agreement Clauses:\n"
            for c in clauses:
                rag_context += f"- [{c.get('clause')}]: {c.get('content')}\n"
            augmented_prompt = f"{user_prompt}\n{rag_context}\nPlease output strictly valid JSON inside ```json``` tags."
        else:
            augmented_prompt = user_prompt

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": augmented_prompt}
        ]
        
        prompt_text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        inputs = self.tokenizer(prompt_text, return_tensors="pt")
        
        t0 = time.time()
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id
            )
        latency = time.time() - t0
        
        generated_ids = outputs[0][inputs["input_ids"].shape[1]:]
        response = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
        return response, latency

def evaluate_predictions(predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate rigorous evaluation metrics across all predictions."""
    total = len(predictions)
    if total == 0:
        return {}
        
    valid_json_count = 0
    agreement_correct = 0
    compliance_correct = 0
    
    tp_violations = 0
    fp_violations = 0
    fn_violations = 0
    
    clause_matches = 0
    total_gt_clauses = 0
    
    latencies = []
    
    for item in predictions:
        latencies.append(item["latency"])
        gt = item["ground_truth"]
        pred = item["parsed_pred"]
        is_valid = item["is_valid_json"]
        
        if is_valid and pred is not None:
            valid_json_count += 1
            
            # Agreement match
            if str(pred.get("agreement", "")).strip().lower() == str(gt.get("agreement", "")).strip().lower():
                agreement_correct += 1
                
            # Compliance binary match
            if pred.get("is_compliant") == gt.get("is_compliant"):
                compliance_correct += 1
                
            # Violation extraction
            gt_types = set(v.get("violation_type", "") for v in gt.get("violations", []))
            pred_types = set(v.get("violation_type", "") for v in pred.get("violations", []))
            
            tp = len(gt_types.intersection(pred_types))
            fp = len(pred_types - gt_types)
            fn = len(gt_types - pred_types)
            
            tp_violations += tp
            fp_violations += fp
            fn_violations += fn
            
            # Clause Citation Matching
            gt_clauses = set(v.get("clause", "") for v in gt.get("violations", []))
            pred_clauses = set(v.get("clause", "") for v in pred.get("violations", []))
            for c in gt_clauses:
                total_gt_clauses += 1
                if any(c.lower() in p.lower() or p.lower() in c.lower() for p in pred_clauses):
                    clause_matches += 1
        else:
            gt_types = set(v.get("violation_type", "") for v in gt.get("violations", []))
            fn_violations += len(gt_types)
            total_gt_clauses += len(gt.get("violations", []))

    precision = tp_violations / (tp_violations + fp_violations) if (tp_violations + fp_violations) > 0 else 0.0
    recall = tp_violations / (tp_violations + fn_violations) if (tp_violations + fn_violations) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    clause_acc = clause_matches / total_gt_clauses if total_gt_clauses > 0 else 0.0
    
    return {
        "total_samples": total,
        "json_validity_rate": round(valid_json_count / total * 100, 2),
        "agreement_accuracy": round(agreement_correct / total * 100, 2),
        "compliance_accuracy": round(compliance_correct / total * 100, 2),
        "violation_precision": round(precision * 100, 2),
        "violation_recall": round(recall * 100, 2),
        "violation_f1": round(f1 * 100, 2),
        "clause_citation_accuracy": round(clause_acc * 100, 2),
        "avg_latency_sec": round(sum(latencies) / len(latencies), 3)
    }

def run_evaluation_harness(num_samples: int = 8):
    """Run full comparative benchmark across configurations."""
    print("=" * 70, flush=True)
    print("BC FILM LABOUR COMPLIANCE - MODEL EVALUATION HARNESS", flush=True)
    print("=" * 70, flush=True)
    print(f"Evaluating {num_samples} test scenarios from {EVAL_FILE}...", flush=True)
    
    test_samples = load_eval_data(EVAL_FILE, max_samples=num_samples)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    configurations = [
        ("Base Model (Zero-Shot)", "base", False),
        ("Base Model + RAG", "base", True),
        ("Open-Source Alt (SmolLM2-360M)", "alt", False),
        ("Fine-Tuned Model (SFT LoRA)", "fine_tuned", False),
        ("Fine-Tuned Model + RAG", "fine_tuned", True),
    ]
    
    all_metrics = {}
    detailed_logs = {}
    
    current_runner = None
    last_model_type = None
    
    for config_name, model_type, use_rag in configurations:
        print(f"\n>>> Running Evaluation for: [{config_name}] <<<", flush=True)
        
        if model_type != last_model_type:
            try:
                current_runner = ModelRunner(model_type)
                last_model_type = model_type
            except Exception as e:
                print(f"Error loading {model_type}: {e}", flush=True)
                continue
                
        predictions = []
        for i, sample in enumerate(test_samples):
            prompt = sample["user_prompt"]
            gt = sample["ground_truth_json"]
            
            raw_resp, latency = current_runner.generate(prompt, use_rag=use_rag)
            parsed, is_valid = extract_json_from_response(raw_resp)
            
            predictions.append({
                "index": i,
                "prompt": prompt,
                "ground_truth": gt,
                "raw_response": raw_resp,
                "parsed_pred": parsed,
                "is_valid_json": is_valid,
                "latency": latency
            })
            print(f"  [{config_name}] Sample {i+1}/{len(test_samples)} ({latency:.2f}s) - JSON Valid: {is_valid}", flush=True)
                
        metrics = evaluate_predictions(predictions)
        all_metrics[config_name] = metrics
        detailed_logs[config_name] = predictions
        print(f"Metrics for {config_name}: {json.dumps(metrics)}", flush=True)
        
    # Save results as JSON, CSV, and Markdown
    metrics_path = RESULTS_DIR / "comparison_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2)
        
    csv_path = RESULTS_DIR / "comparison_metrics.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("Configuration,JSON_Validity_Rate_Pct,Agreement_Accuracy_Pct,Compliance_Accuracy_Pct,Violation_F1_Pct,Clause_Citation_Accuracy_Pct,Avg_Latency_Sec\n")
        for name, m in all_metrics.items():
            f.write(f'"{name}",{m.get("json_validity_rate", 0)},{m.get("agreement_accuracy", 0)},{m.get("compliance_accuracy", 0)},{m.get("violation_f1", 0)},{m.get("clause_citation_accuracy", 0)},{m.get("avg_latency_sec", 0)}\n')
            
    print("\n" + "=" * 70, flush=True)
    print("FINAL COMPARATIVE EVALUATION MATRIX", flush=True)
    print("=" * 70, flush=True)
    header = f"{'Configuration':<32} | {'JSON Val%':<9} | {'Agree%':<7} | {'Compl%':<7} | {'Viol F1%':<9} | {'Clause%':<8} | {'Lat (s)':<7}"
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for name, m in all_metrics.items():
        row = f"{name:<32} | {m.get('json_validity_rate', 0):<9.1f} | {m.get('agreement_accuracy', 0):<7.1f} | {m.get('compliance_accuracy', 0):<7.1f} | {m.get('violation_f1', 0):<9.1f} | {m.get('clause_citation_accuracy', 0):<8.1f} | {m.get('avg_latency_sec', 0):<7.2f}"
        print(row, flush=True)
        
    print(f"\nFull evaluation metrics saved to {metrics_path} and {csv_path}", flush=True)
    return all_metrics

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=8, help="Number of eval samples to benchmark")
    args = parser.parse_args()
    run_evaluation_harness(num_samples=args.samples)
