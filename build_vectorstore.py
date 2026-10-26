import os
import json
from pathlib import Path
import config
from config import VECTOR_DB_DIR, BASE_DIR, EMBEDDING_MODEL_NAME
from extract_knowledge import extract_pdf_text

class LocalSentenceTransformerEF:
    def __init__(self, model_name=EMBEDDING_MODEL_NAME):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, local_files_only=True)

    def name(self) -> str:
        return "local_sentence_transformer"

    def __call__(self, input):
        # Handles list of strings or single string
        if isinstance(input, str):
            input = [input]
        embeddings = self.model.encode(input, convert_to_numpy=True, batch_size=64, show_progress_bar=False)
        return embeddings.tolist()
        
    def embed_query(self, *args, **kwargs):
        inp = kwargs.get("input", args[0] if args else [])
        if isinstance(inp, str):
            inp = [inp]
        return self(inp)
        
    def embed_documents(self, *args, **kwargs):
        inp = kwargs.get("input", args[0] if args else [])
        return self(inp)

def build_vector_store():
    """Index BC film labour agreements into a local Chroma vector database."""
    print("Building Vector Store from Data/ documents...")
    docs = extract_pdf_text()
    
    VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        import chromadb
        
        ef = LocalSentenceTransformerEF()
        client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
        collection = client.get_or_create_collection(
            name="bc_film_labour_agreements",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Upsert documents in batches of 250
        batch_size = 250
        total_docs = len(docs)
        print(f"Upserting {total_docs} chunks from Data/ documents into ChromaDB...")
        
        for i in range(0, total_docs, batch_size):
            batch = docs[i:i + batch_size]
            b_ids = [doc["id"] for doc in batch]
            b_docs = [doc["content"] for doc in batch]
            b_meta = [
                {
                    "agreement": str(doc.get("agreement", "")),
                    "union": str(doc.get("union", "")),
                    "clause": str(doc.get("clause", "")),
                    "topic": str(doc.get("topic", "")),
                    "document": str(doc.get("document", "")),
                    "page": int(doc.get("page", 1))
                }
                for doc in batch
            ]
            
            collection.upsert(
                ids=b_ids,
                documents=b_docs,
                metadatas=b_meta
            )
            print(f"  Indexed batch {i + len(batch)}/{total_docs} chunks...")
            
        print(f"Successfully indexed all {total_docs} document chunks into ChromaDB at {VECTOR_DB_DIR}")
        return client, collection
        
    except Exception as e:
        print(f"ChromaDB indexing error / fallback: {e}")
        # Save json backup for direct lexical / cosine retrieval
        backup_path = VECTOR_DB_DIR / "corpus_backup.json"
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(docs, f, indent=2)
        print(f"Saved fallback knowledge base to {backup_path}")
        return None, None

def query_knowledge_base(query_text: str, n_results: int = 3, distance_threshold: float = 0.65):
    """
    Retrieve top relevant clauses given a shift description or timecard query.
    
    =============================================================================
    COSINE DISTANCE GUARDRAIL:
    ChromaDB collection uses {"hnsw:space": "cosine"}, where:
        Cosine Distance = 1.0 - Cosine Similarity
    
    A strict threshold guardrail (`distance_threshold`, default 0.65) filters out
    retrieved chunks whose distance exceeds 0.65 (similarity < 0.35).
    This ensures that irrelevant or out-of-domain queries do NOT pollute the LLM
    context with ungrounded legal clauses.
    =============================================================================
    """
    try:
        import chromadb
        ef = LocalSentenceTransformerEF()
        client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
        collection = client.get_collection(
            name="bc_film_labour_agreements",
            embedding_function=ef
        )
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        retrieved_docs = []
        if results and "documents" in results and results["documents"]:
            for i, doc_text in enumerate(results["documents"][0]):
                dist = results["distances"][0][i]
                
                # --- COSINE DISTANCE GUARDRAIL FILTER ---
                if distance_threshold is not None and dist > distance_threshold:
                    continue  # Exclude out-of-distribution / low-relevance match
                    
                meta = results["metadatas"][0][i]
                retrieved_docs.append({
                    "content": doc_text,
                    "clause": meta.get("clause", ""),
                    "agreement": meta.get("agreement", ""),
                    "union": meta.get("union", ""),
                    "document": meta.get("document", ""),
                    "page": meta.get("page", 1),
                    "distance": round(float(dist), 4),
                    "similarity": round(1.0 - float(dist), 4)
                })
        return retrieved_docs
    except Exception as e:
        # Fallback keyword matching with lexical guardrail
        docs = extract_pdf_text()
        scores = []
        q_lower = query_text.lower()
        for doc in docs:
            score = 0
            if doc.get("agreement", "").lower() in q_lower:
                score += 5
            if doc.get("union", "").lower() in q_lower:
                score += 5
            for word in doc.get("content", "").lower().split():
                if len(word) > 3 and word in q_lower:
                    score += 1
            if score >= 3:  # Fallback relevance guardrail
                scores.append((score, doc))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scores[:n_results]]

if __name__ == "__main__":
    build_vector_store()
    
    # Test sample queries across multiple agreements
    test_queries = [
        "Principal Actor under UBCP rest period 8.2h turnaround",
        "IATSE Local 891 Dolly Operator meal penalty first meal 7.2 hours",
        "Directors Guild of Canada Third Assistant Director 16 hour workday",
        "What is the best recipe for baking chocolate cookies?"  # Irrelevant query (should be filtered)
    ]
    
    print("\n--- Testing ChromaDB Retrieval & Cosine Distance Guardrail ---")
    for q in test_queries:
        res = query_knowledge_base(q, n_results=2, distance_threshold=0.65)
        print(f"\nQuery: '{q}'")
        if not res:
            print("  [GUARDRAIL TRIGGERED] No documents passed distance threshold <= 0.65 (Query rejected as irrelevant)")
        for idx, r in enumerate(res):
            print(f"  [{idx+1}] Dist: {r.get('distance')} (Sim: {r.get('similarity')}) | Clause: {r.get('clause')}")
            print(f"      Document: {r.get('document')} (Page {r.get('page')})")
            print(f"      Excerpt: {r.get('content')[:140]}...")
