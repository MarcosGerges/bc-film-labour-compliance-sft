import os
import sys
import json
import time
from pathlib import Path

# Add script directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ensure offline and single-threaded tokenization before anything else
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import torch
# Configure optimal CPU thread utilization for Intel 4-core CPU
torch.set_num_threads(4)

from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, TaskType

import config
from config import (
    BASE_MODEL_NAME,
    TRAIN_FILE,
    EVAL_FILE,
    OUTPUT_DIR,
    LORA_R,
    LORA_ALPHA,
    LEARNING_RATE
)

class FilmLabourDataset(Dataset):
    def __init__(self, file_path: Path, tokenizer):
        self.examples = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                messages = record["messages"]
                prompt = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=False
                )
                # Tokenize without fixed padding (dynamic padding in collate)
                tokenized = tokenizer(
                    prompt,
                    truncation=True,
                    max_length=384,
                    return_tensors="pt"
                )
                self.examples.append(tokenized["input_ids"].squeeze(0))
                
    def __len__(self):
        return len(self.examples)
        
    def __getitem__(self, idx):
        return self.examples[idx]

def create_collate_fn(pad_token_id):
    def collate_fn(batch):
        max_len = max(x.size(0) for x in batch)
        # Pad to multiple of 8 for vectorized SIMD efficiency
        if max_len % 8 != 0:
            max_len = ((max_len // 8) + 1) * 8
            
        padded_inputs = []
        attention_masks = []
        labels = []
        
        for item in batch:
            pad_len = max_len - item.size(0)
            if pad_len > 0:
                padded = torch.cat([item, torch.full((pad_len,), pad_token_id, dtype=torch.long)])
                attn = torch.cat([torch.ones(item.size(0), dtype=torch.long), torch.zeros(pad_len, dtype=torch.long)])
                lbl = torch.cat([item, torch.full((pad_len,), -100, dtype=torch.long)])
            else:
                padded = item
                attn = torch.ones(item.size(0), dtype=torch.long)
                lbl = item.clone()
                
            padded_inputs.append(padded)
            attention_masks.append(attn)
            labels.append(lbl)
            
        return {
            "input_ids": torch.stack(padded_inputs),
            "attention_mask": torch.stack(attention_masks),
            "labels": torch.stack(labels)
        }
    return collate_fn

def train_sft():
    print("=" * 65, flush=True)
    print("BC FILM LABOUR COMPLIANCE: SFT LoRA TRAINING", flush=True)
    print("=" * 65, flush=True)
    print(f"Base Model: {BASE_MODEL_NAME}", flush=True)
    print(f"Hardware: Intel CPU ({torch.get_num_threads()} active threads)", flush=True)
    print(f"LoRA: r={LORA_R}, alpha={LORA_ALPHA}, targets=['q_proj', 'v_proj']", flush=True)
    
    start_time = time.time()
    
    # 1. Load Tokenizer
    print("Loading tokenizer from local cache...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_NAME, use_fast=True, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        
    # 2. Build Datasets
    print(f"Loading training data from {TRAIN_FILE}...", flush=True)
    train_dataset = FilmLabourDataset(TRAIN_FILE, tokenizer)
    print(f"Loading validation data from {EVAL_FILE}...", flush=True)
    eval_dataset = FilmLabourDataset(EVAL_FILE, tokenizer)
    print(f"Training samples: {len(train_dataset)}, Validation samples: {len(eval_dataset)}", flush=True)
    
    batch_size = 4
    collate = create_collate_fn(tokenizer.pad_token_id)
    
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate,
        num_workers=0
    )
    eval_loader = DataLoader(
        eval_dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=collate,
        num_workers=0
    )
    
    # 3. Load Model
    print("Loading base causal LM...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_NAME,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True,
        local_files_only=True
    )
    
    # 4. LoRA Setup (target q_proj, v_proj)
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
        bias="none"
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()
    
    # 5. Optimizer & Hyperparameters
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
    epochs = 2
    total_steps = len(train_loader) * epochs
    print(f"\nCommencing training: {epochs} epochs, {len(train_loader)} steps/epoch ({total_steps} total steps)", flush=True)
    
    model.train()
    step = 0
    loss_history = []
    
    for epoch in range(1, epochs + 1):
        for batch_idx, batch in enumerate(train_loader, 1):
            t0 = time.time()
            step += 1
            optimizer.zero_grad()
            
            outputs = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"]
            )
            loss = outputs.loss
            loss.backward()
            
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            
            step_time = time.time() - t0
            loss_val = loss.item()
            loss_history.append({"step": step, "epoch": epoch, "loss": round(loss_val, 4), "step_time_sec": round(step_time, 2)})
            
            # Print every single step for immediate feedback
            pct = (step / total_steps) * 100
            print(f"Step [{step:3d}/{total_steps}] ({pct:5.1f}%) | Epoch {epoch}/{epochs} | Loss: {loss_val:.4f} | Time: {step_time:.2f}s", flush=True)
                
    # 6. Validation Evaluation
    print("\nRunning post-training validation loss evaluation...", flush=True)
    model.eval()
    val_loss = 0.0
    with torch.no_grad():
        for batch in eval_loader:
            outputs = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"]
            )
            val_loss += outputs.loss.item()
    avg_val_loss = val_loss / len(eval_loader)
    print(f"Validation Cross-Entropy Loss: {avg_val_loss:.4f}", flush=True)
    
    # 7. Save Artifacts
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving fine-tuned LoRA weights to {OUTPUT_DIR}...", flush=True)
    model.save_pretrained(str(OUTPUT_DIR))
    tokenizer.save_pretrained(str(OUTPUT_DIR))
    
    history_file = OUTPUT_DIR / "training_history.json"
    train_summary = {
        "model": BASE_MODEL_NAME,
        "epochs": epochs,
        "total_steps": total_steps,
        "final_train_loss": loss_history[-1]["loss"] if loss_history else None,
        "validation_loss": round(avg_val_loss, 4),
        "total_runtime_seconds": round(time.time() - start_time, 2),
        "lora_r": LORA_R,
        "lora_alpha": LORA_ALPHA,
        "loss_history": loss_history
    }
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(train_summary, f, indent=2)
        
    print(f"Training successfully completed in {time.time() - start_time:.2f}s!", flush=True)
    print(f"Metrics and loss history saved to {history_file}", flush=True)

if __name__ == "__main__":
    train_sft()
