import os
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import BASE_MODEL_NAME, OUTPUT_DIR, SYSTEM_PROMPT
from build_vectorstore import query_knowledge_base
from rag_pipeline import build_compliance_graph

PRESET_SCENARIOS = [
    {
        "title": "BCCFU / IATSE 891 - Severe Turnaround Violation & Meal Penalty",
        "role": "Dolly Operator",
        "guild": "BCCFU",
        "union": "IATSE Local 891",
        "rate": 45.98,
        "hours": 14.5,
        "meal_time": 7.2,
        "rest": 6.5,
        "expected_issue": "Rest 6.5h < 10.0h (Turnaround encroached by 3.5h); First meal 7.2h > 6.0h (Delayed meal penalty 1.2h)."
    },
    {
        "title": "UBCP / ACTRA - Extended Performer Shift (>12h) & Meal Delay",
        "role": "Principal Actor",
        "guild": "UBCP",
        "union": "UBCP/ACTRA",
        "rate": 114.71,
        "hours": 13.8,
        "meal_time": 6.8,
        "rest": 11.5,
        "expected_issue": "Workday 13.8h > 12.0h (Excessive performer hours: 1.8h double time); First meal 6.8h > 6.0h (Delayed meal 0.8h)."
    },
    {
        "title": "DGC BC - Fully Compliant Location Management Shift",
        "role": "Assistant Location Manager",
        "guild": "DGC",
        "union": "DGC BC",
        "rate": 36.05,
        "hours": 9.5,
        "meal_time": 5.0,
        "rest": 10.0,
        "expected_issue": "Fully compliant (Rest 10.0h >= 9.0h; Meal 5.0h <= 6.0h; Hours 9.5h <= 15.0h)."
    },
    {
        "title": "BCCFU / Teamsters 155 - Extreme Extended Workday (>15h)",
        "role": "Driver Captain",
        "guild": "BCCFU",
        "union": "Teamsters Local Union No. 155",
        "rate": 45.15,
        "hours": 16.5,
        "meal_time": 5.5,
        "rest": 8.5,
        "expected_issue": "Workday 16.5h > 15.0h (Extended Workday >15 Hours premium rate); Rest 8.5h >= 8.0h."
    }
]

def format_audit_prompt(guild, union, role, rate, hours, meal_time, rest):
    return (
        f"Production Audit Request:\n"
        f"- Guild: {guild} ({union})\n"
        f"- Role: {role}\n"
        f"- Rate: ${rate}/hr\n"
        f"- Total Elapsed Work Time: {hours}h\n"
        f"- First Meal Given: {meal_time}h after call\n"
        f"- Rest Period Between Shifts: {rest}h\n"
        f"Please audit this shift."
    )

def print_audit_banner():
    banner = """
========================================================================
   BRITISH COLUMBIA FILM & TELEVISION LABOUR COMPLIANCE ASSISTANT
         Supervised Fine-Tuned (SFT) Model + LangGraph RAG
========================================================================
Governing Collective Agreements:
  * BCCFU Master Agreement (IATSE 891, Teamsters 155)
  * DGC BC Collective Agreement (Directors Guild of Canada)
  * UBCP / ACTRA BC Master Production Agreement (BCMPA)
  * BC Employment Standards Act (ESA) & WorkSafeBC Fatigue Rules
========================================================================
"""
    print(banner)

def run_interactive_cli(use_rag: bool = True, preset_scenario: int = None):
    print_audit_banner()
    
    # Load model
    print("Loading Fine-Tuned SFT Model...")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    
    tokenizer = AutoTokenizer.from_pretrained(str(OUTPUT_DIR), use_fast=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_NAME,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True
    )
    model = PeftModel.from_pretrained(base_model, str(OUTPUT_DIR))
    model.eval()
    print("Model loaded successfully.\n")

    def model_callable(prompt_text: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text}
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id
            )
        generated_ids = outputs[0][inputs["input_ids"].shape[1]:]
        return tokenizer.decode(generated_ids, skip_special_tokens=True)

    app = build_compliance_graph(model_callable)

    while True:
        if preset_scenario is not None:
            choice = str(preset_scenario)
        else:
            print("\nSelect an option:")
            for idx, scenario in enumerate(PRESET_SCENARIOS, 1):
                print(f"  [{idx}] {scenario['title']}")
            print("  [C] Custom Timecard Scenario")
            print("  [Q] Quit")
            
            choice = input("\nEnter choice (1-4, C, Q): ").strip().upper()
            
        if choice == "Q":
            print("Exiting Compliance Assistant. Good wrap!")
            break
            
        if choice in ["1", "2", "3", "4"]:
            sc = PRESET_SCENARIOS[int(choice) - 1]
            print(f"\n--- Testing Scenario: {sc['title']} ---")
            print(f"Role: {sc['role']} | Union: {sc['union']} | Rate: ${sc['rate']}/hr")
            print(f"Shift: {sc['hours']}h | 1st Meal: {sc['meal_time']}h | Turnaround Rest: {sc['rest']}h")
            print(f"Expected Ground Truth: {sc['expected_issue']}\n")
            query = format_audit_prompt(sc['guild'], sc['union'], sc['role'], sc['rate'], sc['hours'], sc['meal_time'], sc['rest'])
        elif choice == "C":
            print("\n--- Enter Custom Timecard Details ---")
            role = input("Role (e.g. Dolly Operator, Principal Actor, Assistant Location Manager): ").strip()
            guild = input("Agreement / Guild (BCCFU, UBCP, DGC): ").strip().upper()
            union = input("Union Local (e.g. IATSE Local 891, UBCP/ACTRA, DGC BC, Teamsters 155): ").strip()
            rate = float(input("Scale hourly wage rate ($): ").strip())
            hours = float(input("Shift duration (hours): ").strip())
            meal_time = float(input("First meal break call time (hours after start): ").strip())
            rest = float(input("Turnaround rest period before next shift (hours): ").strip())
            query = format_audit_prompt(guild, union, role, rate, hours, meal_time, rest)
        else:
            print("Invalid choice, please retry.")
            continue

        print("\nExecuting LangGraph compliance workflow...")
        initial_state = {
            "query": query,
            "use_rag": use_rag,
            "retrieved_clauses": [],
            "prompt": "",
            "model_name_or_path": str(OUTPUT_DIR),
            "raw_output": "",
            "parsed_report": None,
            "is_valid_json": False,
            "error": None
        }
        
        final_state = app.invoke(initial_state)
        
        print("\n" + "=" * 60)
        print("AUDIT REPORT (LangGraph Pipeline Output):")
        print("=" * 60)
        if final_state.get("retrieved_clauses"):
            print("Grounding Clauses Retrieved via RAG:")
            for c in final_state["retrieved_clauses"]:
                print(f"  * [{c.get('clause')}]: {c.get('content')[:90]}...")
            print("-" * 60)
            
        if final_state.get("is_valid_json"):
            report = final_state["parsed_report"]
            status = "COMPLIANT" if report.get("is_compliant") else "VIOLATIONS DETECTED"
            print(f"Status: {status}")
            print(f"Agreement: {report.get('agreement')} | Role: {report.get('classification')}")
            violations = report.get("violations", [])
            if violations:
                print(f"\nIdentified Violations ({len(violations)}):")
                for v in violations:
                    print(f"  • Type: {v.get('violation_type')}")
                    print(f"    Clause: {v.get('clause')}")
                    print(f"    Penalty/Hours Affected: {v.get('hours_affected')}h")
                    print(f"    Description: {v.get('description')}")
            else:
                print("No collective agreement infractions detected.")
        else:
            print("Raw Model Output (JSON Parse Warning):")
            print(final_state.get("raw_output"))
        print("=" * 60)
        
        if preset_scenario is not None:
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BC Film Labour Compliance Assistant Demo")
    parser.add_argument("--no-rag", action="store_true", help="Disable RAG clause retrieval")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], default=None, help="Directly run preset scenario (1-4)")
    args = parser.parse_args()
    run_interactive_cli(use_rag=not args.no_rag, preset_scenario=args.scenario)
