import os
import json
import hashlib
import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# --- IMPORTS ---
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
# from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder

load_dotenv()

app = FastAPI()

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. LOAD MODELS ---
print("⏳ Loading Models... (This may take 30s on first run)")

# A. Embedding Model (for Vector Search)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# B. Cross-Encoder (The "Re-Ranker")
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

# C. LLM (Gemini)
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

print("✅ Models Loaded!")

# --- 3. CACHING SETUP ---
DB_FILE = "cache.db"
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS policy_cache
                 (url_hash TEXT PRIMARY KEY, analysis_json TEXT)''')
    conn.commit()
    conn.close()
init_db()

def get_cached_analysis(text):
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT analysis_json FROM policy_cache WHERE url_hash=?", (text_hash,))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

def save_to_cache(text, result):
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO policy_cache VALUES (?, ?)", 
              (text_hash, json.dumps(result)))
    conn.commit()
    conn.close()

# --- 4. LOGIC ---
USER_CONSTITUTION = [
    "Does the policy allow them to sell my data to third parties?",
    "Is there a mandatory binding arbitration clause?",
    "Does it force me to waive my right to a class action lawsuit?",
    "Do they claim a license to use my content (IP) for any purpose?",
    "Can they track my location when I am not using the app?",
    "Can they change the terms without notifying me first?"
]

class PolicyRequest(BaseModel):
    url: str
    text: str

@app.post("/analyze")
async def analyze_policy(request: PolicyRequest):
    try:
        print("\n" + "="*30)
        print(f"🔍 ANALYZING: {request.url}")
        
        # Check Cache
        cached = get_cached_analysis(request.text)
        if cached:
            print("⚡ CACHE HIT! Returning saved result.")
            return cached

        if len(request.text) < 200:
             return {"safety_score": 0, "analysis": {"Error": "Text too short."}}

        # --- STEP A: PREPARE RETRIEVERS ---
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
        chunks = text_splitter.split_text(request.text)

        # 1. Keyword Search (BM25)
        bm25_retriever = BM25Retriever.from_texts(chunks)
        bm25_retriever.k = 5

        # 2. Vector Search (FAISS)
        faiss_vectorstore = FAISS.from_texts(chunks, embeddings)
        faiss_retriever = faiss_vectorstore.as_retriever(search_kwargs={"k": 5})

        # --- STEP B: RETRIEVE & RE-RANK LOOP ---
        unique_context = set()
        
        for concern in USER_CONSTITUTION:
            # 1. Manual Ensemble Retrieval
            # We pull docs from BOTH systems manually
            docs_bm25 = bm25_retriever.invoke(concern)
            docs_faiss = faiss_retriever.invoke(concern)
            
            # Pool them together (Candidate Generation)
            all_docs = docs_bm25 + docs_faiss
            
            # Deduplicate (remove exact duplicates)
            seen_content = set()
            unique_candidates = []
            for doc in all_docs:
                if doc.page_content not in seen_content:
                    seen_content.add(doc.page_content)
                    unique_candidates.append(doc.page_content)
            
            # 2. Re-Rank (Cross Encoder)
            # We ask the model: "How relevant is this candidate to the concern?"
            pairs = [[concern, doc_text] for doc_text in unique_candidates]
            scores = reranker.predict(pairs)
            
            # Sort by score (highest relevance first)
            scored_docs = sorted(zip(unique_candidates, scores), key=lambda x: x[1], reverse=True)
            
            # Take the Top 2 Winners
            top_docs = [doc for doc, score in scored_docs[:2]]
            unique_context.update(top_docs)

        combined_context = "\n---\n".join(unique_context)

        # --- STEP C: GENERATE (Batch) ---
        questions_str = "\n".join([f"{i+1}. {q}" for i, q in enumerate(USER_CONSTITUTION)])
        
        
        prompt = f"""
        You are a strict Privacy Auditor.
        Analyze the following Terms of Service text.
        
        CONTEXT FROM DOCUMENT:
        {combined_context}
        
        YOUR TASK:
        Answer the following questions.
        
        QUESTIONS:
        {questions_str}
        
        OUTPUT FORMAT:
        Return strictly a valid JSON object. Keys are the questions.
        Values MUST follow this format:
        - If SAFE: "NO"
        - If UNSAFE: "YES. [Insert a short 1-sentence quote or explanation from the text]"
        
        IMPORTANT:
        - Do NOT just say "YES". You MUST explain WHY.
        - Do NOT use markdown code blocks. Just raw JSON.
        """
        
        print("🚀 Sending to AI...")
        response = llm.invoke(prompt)
        
        # Clean JSON
        raw_content = response.content.strip()
        if raw_content.startswith("```json"): raw_content = raw_content[7:]
        if raw_content.endswith("```"): raw_content = raw_content[:-3]
        
        results = json.loads(raw_content)

        # --- STEP D: FINISH ---
        bad_flags = sum(1 for ans in results.values() if "YES" in str(ans).upper())
        score = max(0, 100 - (bad_flags * 15))

        final_response = {"safety_score": score, "analysis": results}
        save_to_cache(request.text, final_response)
        
        print(f"🏁 FINAL SCORE: {score}%")
        return final_response

    except Exception as e:
        print(f"❌ ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)