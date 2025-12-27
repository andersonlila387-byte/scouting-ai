import os
import time
import random
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from dotenv import load_dotenv
import hashlib

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
# 1. Get your free API key from: https://aistudio.google.com/app/apikey
# 2. Paste it inside the quotes below (e.g. "AIzaSy...")
MANUAL_API_KEY  = "AIzaSyCf4fpA6gn17OO7IW1hZRgbL4TfVIgC8mU"

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    API_KEY = MANUAL_API_KEY

app = FastAPI(title="SiteScout CRM Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- AI SETUP ---
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
else:
    model = None

# --- MODELS ---
class ScoutRequest(BaseModel):
    industry: str
    location: str
    page: int = 1  # Added for pagination

class VerifyEmailRequest(BaseModel):
    email: str

class BusinessProfile(BaseModel):
    id: str
    name: str
    industry: str
    location: str
    website: Optional[str] = None
    phone: str
    email: Optional[str] = None
    social_media: Optional[Dict[str, str]] = {}
    source_url: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None

class AnalyzeRequest(BaseModel):
    business_name: str
    industry: str
    location: str
    website: Optional[str] = None

class AnalysisResult(BaseModel):
    audit_score: int
    pain_points: List[str]
    improvements: List[str]
    outreach_message: str

# --- SERVICES ---

def mock_scout_service(industry: str, location: str, page: int) -> List[dict]:
    """
    Simulates finding businesses. 
    Page number changes the random seed to get 'new' results.
    """
    time.sleep(1.0) 
    
    # Use page to offset random generation so we get different results
    random.seed(f"{industry}{location}{page}")
    
    base_names = ["Apex", "Elite", "Prime", "Cornerstone", "Trusted", "Summit", "Vanguard", "Pinnacle", "NextLevel", "Local"]
    suffixes = ["Solutions", "Services", "Inc", "Co", "Group", "Partners", "Associates", "Pros"]
    
    results = []
    # Generate 3 new leads per 'page' load
    for i in range(10):
        has_site = random.choice([True, False, False, False, False]) # 80% chance of no site
        
        # Create unique name based on page
        base = random.choice(base_names)
        suffix = random.choice(suffixes)
        # Ensure name uniqueness for the demo
        name = f"{base} {industry.capitalize()} {suffix}"
        if page > 1:
            name += f" {page}"

        sanitized = name.replace(" ", "").lower()
        email = f"contact@{base.lower()}{industry.lower()}.com" if has_site else f"{sanitized}@gmail.com"
        
        socials = {}
        if random.random() > 0.3: socials['linkedin'] = f"https://linkedin.com/company/{sanitized}"
        if random.random() > 0.6: socials['twitter'] = f"https://twitter.com/{sanitized}"
        if random.random() > 0.6: socials['facebook'] = f"https://facebook.com/{sanitized}"

        source_url = f"https://www.google.com/search?q={name.replace(' ', '+')}+{location.replace(' ', '+')}"

        rating = round(random.uniform(3.5, 4.9), 1)
        review_count = random.randint(10, 500)

        results.append({
            "id": f"biz_{hash(name)}", # logical ID
            "name": name,
            "industry": industry,
            "location": location,
            "website": f"www.{base.lower()}{industry.lower()}.com" if has_site else None,
            "phone": f"(555) {random.randint(100, 999)}-{random.randint(1000, 9999)}",
            "email": email,
            "social_media": socials,
            "source_url": source_url,
            "rating": rating,
            "review_count": review_count
        })
    return results

def ai_scout_service(industry: str, location: str, page: int) -> List[dict]:
    if not model:
        return mock_scout_service(industry, location, page)

    prompt = f"""
    You are a business intelligence agent.
    Task: List 10 REAL existing businesses for the industry '{industry}' in '{location}' that likely DO NOT have a website or have a low digital presence.
    This is for a CRM demo. If exact real data is unavailable, generate highly plausible realistic examples.
    
    CRITERIA:
    1. Prioritize businesses without a website.
    2. Include their estimated Google Maps rating and review count.
    
    Page {page} of results.
    
    Return a JSON array of objects with these exact keys:
    - name (Business Name)
    - industry (The industry)
    - location (City, State)
    - website (URL or null)
    - phone (Phone number)
    - email (Public contact email or null)
    - rating (Float, e.g. 4.5)
    - review_count (Integer)
    
    JSON ONLY. No markdown formatting.
    """
    
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        import json
        data = json.loads(response.text)
        
        results = []
        for item in data:
            # Create a deterministic ID based on name
            hash_object = hashlib.md5(item.get('name', '').encode())
            item_id = f"biz_{hash_object.hexdigest()[:10]}"
            
            name = item.get('name', 'Unknown')
            source_url = f"https://www.google.com/search?q={name.replace(' ', '+')}+{location.replace(' ', '+')}"
            
            # Generate plausible social links since AI often skips them to save tokens
            sanitized = name.replace(" ", "").lower()
            socials = {
                'linkedin': f"https://linkedin.com/company/{sanitized}",
                'twitter': f"https://twitter.com/{sanitized}"
            }

            results.append({
                "id": item_id,
                "name": name,
                "industry": item.get("industry", industry),
                "location": item.get("location", location),
                "website": item.get("website"),
                "phone": item.get("phone", "N/A"),
                "email": item.get("email"),
                "social_media": socials,
                "source_url": source_url,
                "rating": item.get("rating"),
                "review_count": item.get("review_count")
            })
        return results
    except Exception as e:
        print(f"AI Scout Error: {e}")
        return mock_scout_service(industry, location, page)

def generate_audit_and_message(data: AnalyzeRequest) -> dict:
    if not model:
        # Fallback if no API key
        return {
            "audit_score": 45,
            "pain_points": ["No API Key Detected", "Cannot analyze real data", "Please set GEMINI_API_KEY"],
            "improvements": ["Add API Key to backend", "Restart server"],
            "outreach_message": "System Error: Please configure the AI backend."
        }

    website_status = f"They currently have a website: {data.website}" if data.website else "They currently DO NOT have a website."
    
    prompt = f"""
    Act as a Digital Marketing Consultant.
    Target: {data.business_name} ({data.industry}) in {data.location}.
    Status: {website_status}
    
    1. Audit:
    - Score (0-100). If no website, max 30.
    - 3 Pain Points (concise).
    - 3 Improvements we can offer.
    
    2. Outreach:
    - Write a short, punchy cold email.
    - Subject line included.
    
    Return JSON:
    {{
        "audit_score": int,
        "pain_points": [str],
        "improvements": [str],
        "outreach_message": str
    }}
    """
    
    max_retries = 3
    retry_delay = 60

    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            import json
            return json.loads(response.text)
        except Exception as e:
            print(f"AI Error (Attempt {attempt + 1}): {e}")
            if "429" in str(e) or "Quota exceeded" in str(e):
                if attempt < max_retries - 1:
                    print(f"Rate limit hit. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return {
                        "audit_score": 0,
                        "pain_points": ["Rate Limit Hit"],
                        "improvements": ["Wait 60 seconds", "Try again"],
                        "outreach_message": "Google Gemini API Rate Limit Exceeded. Please wait a minute and try again."
                    }
            return {
                "audit_score": 0,
                "pain_points": ["AI Error"],
                "improvements": ["Check console logs"],
                "outreach_message": "Error generating message."
            }

# --- ENDPOINTS ---

@app.get("/")
def read_root():
    return {"status": "SiteScout CRM Active"}

@app.post("/api/scout", response_model=List[BusinessProfile])
def scout(request: ScoutRequest):
    print(f"Scouting page {request.page} for {request.industry}")
    return ai_scout_service(request.industry, request.location, request.page)

@app.post("/api/analyze", response_model=AnalysisResult)
def analyze(request: AnalyzeRequest):
    return generate_audit_and_message(request)

@app.post("/api/verify-email")
def verify_email(request: VerifyEmailRequest):
    time.sleep(0.5) # Simulate network check
    email = request.email.lower().strip()
    
    # Deterministic simulation: 20% chance of being invalid for demo purposes
    import hashlib
    h = int(hashlib.md5(email.encode()).hexdigest(), 16)
    return {"status": "invalid" if h % 5 == 0 else "valid"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)