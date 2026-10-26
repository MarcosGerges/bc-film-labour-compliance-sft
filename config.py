import os
from pathlib import Path

# Force offline mode so huggingface loads exclusively from local cache
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Data"
TRAIN_FILE = BASE_DIR / "train.jsonl"
EVAL_FILE = BASE_DIR / "eval.jsonl"
VECTOR_DB_DIR = BASE_DIR / "chroma_db"
OUTPUT_DIR = BASE_DIR / "models" / "qwen2.5-0.5b-bc-film-lora"
RESULTS_DIR = BASE_DIR / "eval_results"

# Models
# Primary model: Qwen2.5-0.5B-Instruct (fast, fits comfortably in CPU memory, outstanding instruction/json ability)
BASE_MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"
# Alternative model for baseline comparison: SmolLM2-360M-Instruct
ALT_MODEL_NAME = "HuggingFaceTB/SmolLM2-360M-Instruct"
# Embedding model for RAG
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# SFT Hyperparameters (tuned for CPU execution efficiency & stability)
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

LEARNING_RATE = 2e-4
NUM_TRAIN_EPOCHS = 3
PER_DEVICE_TRAIN_BATCH_SIZE = 4
GRADIENT_ACCUMULATION_STEPS = 2
MAX_SEQ_LENGTH = 512
WARMUP_RATIO = 0.05
WEIGHT_DECAY = 0.01

# System prompt used in training and inference
SYSTEM_PROMPT = (
    "You are a specialized British Columbia Film & Television Labor Compliance Assistant. "
    "Analyze timesheets and shift reports against BC collective agreements and output structured JSON audits."
)
