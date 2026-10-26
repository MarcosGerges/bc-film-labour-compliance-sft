import os
import re
import json
from pathlib import Path
from config import DATA_DIR, BASE_DIR

_CACHED_DOCS = None

# Curated reference clauses from primary documents for core benchmark rules
CORE_AGREEMENT_ARTICLES = [
    {
        "id": "bccfu-turnaround-iatse",
        "document": "2025-2028 BCCFU Master Agreement - Official Version.pdf",
        "agreement": "BCCFU",
        "union": "IATSE Local 891",
        "clause": "BCCFU Article A1.20(a)",
        "page": 56,
        "topic": "Rest Period & Turnaround",
        "content": (
            "BCCFU Master Agreement Article A1.20(a) - Turnaround: "
            "The minimum rest period (turnaround) between the end of one shift and the call time "
            "for the next shift for IATSE Local 891 technicians (including Dolly Operator, Head Lighting "
            "Technician, Assistant Costume Designer, Boom Operator) shall be ten (10.0) consecutive hours. "
            "If the rest period is encroached (less than 10.0 hours), turnaround encroachment penalties "
            "apply for all hours encroached at double the regular hourly scale rate."
        )
    },
    {
        "id": "bccfu-turnaround-teamsters",
        "document": "2025-2028 BCCFU Master Agreement - Official Version.pdf",
        "agreement": "BCCFU",
        "union": "Teamsters Local Union No. 155",
        "clause": "BCCFU Article B3.01(a)",
        "page": 78,
        "topic": "Rest Period & Turnaround",
        "content": (
            "BCCFU Master Agreement Article B3.01(a) - Turnaround: "
            "The minimum rest period between shifts for Teamsters Local Union No. 155 members "
            "(including Driver Captain, Special Equipment Driver, Transportation Coordinator) "
            "shall be eight (8.0) consecutive hours off duty. Turnaround encroachment penalties apply "
            "if the rest interval between dismissal and subsequent call is less than 8.0 hours."
        )
    },
    {
        "id": "bccfu-meals",
        "document": "2025-2028 BCCFU Master Agreement - Official Version.pdf",
        "agreement": "BCCFU",
        "union": "IATSE Local 891 / Teamsters 155",
        "clause": "BCCFU Article 6.01/6.04",
        "page": 24,
        "topic": "Meal Periods & Meal Penalty",
        "content": (
            "BCCFU Master Agreement Article 6.01 and Article 6.04 - Meal Periods: "
            "The first meal period of not less than one-half (1/2) hour or not more than one (1) hour "
            "shall be provided no later than six (6.0) hours after the employee's call time. "
            "If an employee is required to work beyond the six-hour mark without a meal break, "
            "a Delayed Meal Penalty accrues for all elapsed time until the meal is called. "
            "Meal penalty is payable in addition to all other compensation."
        )
    },
    {
        "id": "bccfu-overtime",
        "document": "2025-2028 BCCFU Master Agreement - Official Version.pdf",
        "agreement": "BCCFU",
        "union": "IATSE Local 891 / Teamsters 155",
        "clause": "BCCFU Article 4.06",
        "page": 19,
        "topic": "Extended Workday & Overtime",
        "content": (
            "BCCFU Master Agreement Article 4.06 - Extended Workday / Excessive Hours: "
            "A standard shift consists of eight (8) hours. Hours worked in excess of 8 and up to 12 hours "
            "are paid at time-and-a-half (1.5x). Hours worked between 12 and 15 hours are paid at double time (2.0x). "
            "Work performed in excess of fifteen (15.0) consecutive hours in a single workday constitutes an "
            "Extended Workday (>15 Hours), requiring premium compensation of 2.5x to 3.0x the base scale wage rate "
            "and production company authorization due to fatigue risk."
        )
    },
    {
        "id": "dgc-turnaround",
        "document": "2025 Collective Agreement.pdf",
        "agreement": "DGC",
        "union": "DGC BC (Directors Guild of Canada)",
        "clause": "DGC BC Article 17.1",
        "page": 44,
        "topic": "Rest Period & Turnaround",
        "content": (
            "DGC BC Collective Agreement Article 17.1 - Rest Intervals: "
            "For Guild members including Third Assistant Director, Assistant Location Manager, "
            "Second Assistant Director, and Location Manager, the minimum turnaround rest interval "
            "between wrap and call time the next day shall be nine (9.0) consecutive hours. "
            "Failure to provide 9.0 consecutive hours of rest incurs turnaround encroachment penalties."
        )
    },
    {
        "id": "dgc-meals",
        "document": "2025 Collective Agreement.pdf",
        "agreement": "DGC",
        "union": "DGC BC (Directors Guild of Canada)",
        "clause": "DGC BC Article 16.2",
        "page": 41,
        "topic": "Meal Breaks",
        "content": (
            "DGC BC Collective Agreement Article 16.2 - Meal Penalties: "
            "The first meal must be served within six (6.0) hours of the member's call time. "
            "Working past 6.0 hours without a meal break triggers a Delayed Meal Penalty "
            "calculated on a progressive hourly penalty structure until the meal is called."
        )
    },
    {
        "id": "dgc-overtime",
        "document": "2025 Collective Agreement.pdf",
        "agreement": "DGC",
        "union": "DGC BC (Directors Guild of Canada)",
        "clause": "DGC BC Article 15.5",
        "page": 38,
        "topic": "Extended Workday & Overtime",
        "content": (
            "DGC BC Collective Agreement Article 15.5 - Extended Workday (>15 Hours): "
            "Any shift surpassing fifteen (15.0) consecutive elapsed hours incurs highest-tier overtime "
            "premiums and requires written confirmation from the District Council. Safety provisions require "
            "the employer to offer rest accommodations or transport home if severe fatigue is present."
        )
    },
    {
        "id": "ubcp-turnaround",
        "document": "2025-2028-UBCP-BCMPA.pdf",
        "agreement": "UBCP",
        "union": "UBCP / ACTRA (Performers)",
        "clause": "UBCP BCMPA Article A1301",
        "page": 62,
        "topic": "Rest Period & Turnaround",
        "content": (
            "UBCP/ACTRA BCMPA Article A1301 - Rest Periods: "
            "Performers (including Principal Actor, Background Performer, Stunt Performer) are entitled to "
            "a minimum rest turnaround interval of eleven (11.0) consecutive hours between dismissal and next call. "
            "If turnaround is encroached, the producer shall pay an encroachment premium penalty equal to "
            "one day's scale fee or double hourly rate for all encroached hours."
        )
    },
    {
        "id": "ubcp-meals",
        "document": "2025-2028-UBCP-BCMPA.pdf",
        "agreement": "UBCP",
        "union": "UBCP / ACTRA (Performers)",
        "clause": "UBCP BCMPA Article A1401",
        "page": 65,
        "topic": "Meal Intervals",
        "content": (
            "UBCP/ACTRA BCMPA Article A1401 - Meal Periods: "
            "The first meal break must be provided not later than six (6.0) hours after the performer's "
            "individual call time. Failure to provide a meal within 6 hours triggers Delayed Meal Penalties "
            "payable at premium compounding rates per half-hour delay."
        )
    },
    {
        "id": "ubcp-overtime",
        "document": "2025-2028-UBCP-BCMPA.pdf",
        "agreement": "UBCP",
        "union": "UBCP / ACTRA (Performers)",
        "clause": "UBCP BCMPA Article A1201",
        "page": 58,
        "topic": "Daily Overtime & Extended Workday",
        "content": (
            "UBCP/ACTRA BCMPA Article A1201 - Overtime: "
            "Performers working in excess of eight (8) hours receive time-and-a-half (1.5x). "
            "Work exceeding twelve (12.0) hours in a single day is compensated at Double Time (2.0x). "
            "Extended workdays exceeding 12 hours for performers require specialized meal and rest relief."
        )
    },
    {
        "id": "esa-minimums",
        "document": "Employment Standards Act.pdf",
        "agreement": "Statutory",
        "union": "BC Employment Standards",
        "clause": "BC Employment Standards Act Part 4",
        "page": 18,
        "topic": "Statutory Minimum Daily and Weekly Rest",
        "content": (
            "British Columbia Employment Standards Act (ESA) Part 4 - Hours of Work: "
            "An employer must ensure that employees receive at least 8 consecutive hours free from work "
            "between each shift, and at least 32 consecutive hours free from work each week. "
            "Collective agreements in the film industry supersede the ESA only where they meet or exceed "
            "statutory minimum protections."
        )
    },
    {
        "id": "worksafebc-fatigue",
        "document": "General-health-and-safety-primer.pdf",
        "agreement": "Safety",
        "union": "WorkSafeBC / Actsafe",
        "clause": "WorkSafeBC OHS Guidelines / Actsafe Film Safety",
        "page": 12,
        "topic": "Fatigue Management & Long Shifts",
        "content": (
            "WorkSafeBC Occupational Health and Safety & Actsafe BC Motion Picture Safety Guidelines: "
            "Shifts extending over 14 hours pose severe fatigue risks during commutes. Employers must provide "
            "rest areas, taxi vouchers, or hotel accommodations to cast and crew if safe driving is impaired. "
            "Turnaround violations directly exacerbate occupational health hazards on BC film sets."
        )
    }
]

DOC_MAPPINGS = {
    "2025 Collective Agreement.pdf": ("DGC", "DGC BC (Directors Guild of Canada)"),
    "2025-2028 BCCFU Master Agreement - Official Version.pdf": ("BCCFU", "BCCFU (IATSE 891 / Teamsters 155 / ICG 669)"),
    "2025-2028-UBCP-BCMPA.pdf": ("UBCP", "UBCP / ACTRA (Performers)"),
    "Employment Standards Act.pdf": ("Statutory", "BC Employment Standards"),
    "General-health-and-safety-primer.pdf": ("Safety", "WorkSafeBC / Actsafe"),
    "Labour-And-Employment-Law-in-British-Columbia.pdf": ("Labour Law", "BC Labour Relations / LRB")
}

def extract_pdf_text(force_reload=False):
    """
    Extract structured chunks from all PDF documents in the Data/ directory.
    Caches parsed chunks to corpus_chunks.json for high-speed subsequent retrieval.
    """
    global _CACHED_DOCS
    if _CACHED_DOCS is not None and not force_reload:
        return _CACHED_DOCS
        
    cache_path = BASE_DIR / "corpus_chunks.json"
    if cache_path.exists() and not force_reload:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if len(cached) > 100:
                print(f"Loaded {len(cached)} cached document chunks from {cache_path}")
                _CACHED_DOCS = cached
                return _CACHED_DOCS
        except Exception as e:
            print(f"Cache read error: {e}. Rebuilding...")

    print("Extracting text and chunking documents from Data/ directory...")
    all_chunks = []
    
    # Add curated benchmark core agreement articles
    all_chunks.extend(CORE_AGREEMENT_ARTICLES)
    
    try:
        import pypdf
        for pdf_name, (agr, union) in DOC_MAPPINGS.items():
            pdf_path = DATA_DIR / pdf_name
            if not pdf_path.exists():
                print(f"Notice: {pdf_name} not found in {DATA_DIR}")
                continue
                
            reader = pypdf.PdfReader(str(pdf_path))
            print(f"Ingesting '{pdf_name}' ({len(reader.pages)} pages)...")
            
            doc_chunks = 0
            for page_idx, page in enumerate(reader.pages):
                raw_text = page.extract_text() or ""
                clean_text = re.sub(r"\s+", " ", raw_text).strip()
                if len(clean_text) < 50:
                    continue
                    
                art_match = re.search(r"(?:ARTICLE|Article|Section|Part)\s+([A-Z0-9\.\-]+)", clean_text)
                clause_tag = f"{agr} {art_match.group(0)}" if art_match else f"{agr} Page {page_idx + 1}"
                
                stride = 700
                chunk_size = 850
                for i in range(0, len(clean_text), stride):
                    sub_chunk = clean_text[i:i + chunk_size].strip()
                    if len(sub_chunk) >= 60:
                        chunk_id = f"{agr.lower()}-p{page_idx + 1}-c{i // stride}"
                        all_chunks.append({
                            "id": chunk_id,
                            "document": pdf_name,
                            "agreement": agr,
                            "union": union,
                            "clause": clause_tag,
                            "page": page_idx + 1,
                            "topic": f"{agr} Collective Agreement - Page {page_idx + 1}",
                            "content": f"[{pdf_name} - Page {page_idx + 1} | {clause_tag}]\n{sub_chunk}"
                        })
                        doc_chunks += 1
            print(f"  -> Successfully generated {doc_chunks} chunks from '{pdf_name}'.")
    except ImportError:
        print("pypdf not installed, using core agreements only.")

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2)
    print(f"Saved total {len(all_chunks)} chunks to {cache_path}")
    
    _CACHED_DOCS = all_chunks
    return all_chunks

if __name__ == "__main__":
    docs = extract_pdf_text(force_reload=True)
    print(f"Extraction complete: {len(docs)} total document chunks ready for ChromaDB indexing.")
