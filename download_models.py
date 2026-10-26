import sys
import time
from transformers import AutoTokenizer, AutoModelForCausalLM

def download_all():
    print("=== Downloading Base Model: Qwen/Qwen2.5-0.5B-Instruct ===", flush=True)
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")
    print(f"Base Tokenizer downloaded in {time.time()-t0:.2f}s", flush=True)
    
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")
    print(f"Base Model downloaded in {time.time()-t0:.2f}s", flush=True)
    
    print("\n=== Downloading Alternative Model: HuggingFaceTB/SmolLM2-360M-Instruct ===", flush=True)
    t0 = time.time()
    tok_alt = AutoTokenizer.from_pretrained("HuggingFaceTB/SmolLM2-360M-Instruct")
    print(f"Alt Tokenizer downloaded in {time.time()-t0:.2f}s", flush=True)
    
    t0 = time.time()
    model_alt = AutoModelForCausalLM.from_pretrained("HuggingFaceTB/SmolLM2-360M-Instruct")
    print(f"Alt Model downloaded in {time.time()-t0:.2f}s", flush=True)
    
    print("\n=== Downloading Embedding Model: sentence-transformers/all-MiniLM-L6-v2 ===", flush=True)
    from sentence_transformers import SentenceTransformer
    t0 = time.time()
    emb = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    print(f"Embedding model downloaded in {time.time()-t0:.2f}s", flush=True)
    print("\nALL MODELS DOWNLOADED AND CACHED SUCCESSFULLY!", flush=True)

if __name__ == "__main__":
    download_all()
