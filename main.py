import os
import json
import uvicorn
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import anthropic
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="Clarion Care AI Supply Chain Coordinator")
templates = Jinja2Templates(directory="templates")

# Initialize Claude client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def load_json(path: str, default=None):
    """Safely load JSON with fallback"""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load {path}: {e}")
        return default if default is not None else []

# Load mock data
suppliers_data = load_json('data/suppliers.json', [])
emails_data = load_json('data/email_threads.json', [])
parsed_data = load_json('data/parsed_communications.json', [])
draft_responses = load_json('data/draft_responses.json', [])

class EmailAnalysisRequest(BaseModel):
    email_content: str

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main supply chain coordinator dashboard"""
    
    # Calculate metrics
    total_suppliers = len(suppliers_data)
    active_rfqs = len([p for p in parsed_data if p.get('status') == 'pending_quote'])
    overdue_items = len([p for p in parsed_data if p.get('priority') == 'urgent'])
    time_saved = 3.5  # Hours saved this week
    
    # Get recent activity for timeline
    recent_activity = []
    for email in emails_data[:5]:  # Last 5 emails
        recent_activity.append({
            'time': email.get('received_at', '2 hours ago'),
            'type': 'email_processed',
            'description': f"Processed email from {email.get('supplier_name', 'Unknown')} - {email.get('subject', 'No subject')[:50]}",
            'status': 'completed'
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_suppliers": total_suppliers,
        "active_rfqs": active_rfqs,
        "overdue_items": overdue_items,
        "time_saved": time_saved,
        "suppliers": suppliers_data,
        "parsed_data": parsed_data,
        "recent_activity": recent_activity,
        "draft_responses": draft_responses[:3]  # Show top 3 drafts
    })

@app.get("/email-processor", response_class=HTMLResponse)
async def email_processor(request: Request):
    """Email processing interface"""
    # Load example email content
    example_email = load_json('data/example_email.json', {}).get('content', '')
    
    return templates.TemplateResponse("email_processor.html", {
        "request": request,
        "example_email": example_email
    })

@app.post("/process-email")
async def process_email(email_content: str = Form(...)):
    """Process supplier email with Claude API"""
    if not email_content.strip():
        raise HTTPException(status_code=400, detail="No email content provided")
    
    try:
        # System prompt for supply chain email analysis
        system_prompt = """You are an AI supply chain coordinator for Clarion Care, a medical device company. 
        
Analyze supplier emails and extract key information in JSON format:
{
  "supplier_name": "company name",
  "email_type": "quote_request|quote_response|shipment_update|lead_time_update|general",
  "components": [
    {
      "name": "component name",
      "part_number": "if provided",
      "quantity": number,
      "unit_price": number or null,
      "lead_time_weeks": number or null,
      "status": "quoted|ordered|shipped|delayed"
    }
  ],
  "key_dates": {
    "quote_deadline": "YYYY-MM-DD or null",
    "expected_ship": "YYYY-MM-DD or null",
    "delivery_date": "YYYY-MM-DD or null"
  },
  "priority_level": "low|medium|high|urgent",
  "action_required": "response_needed|follow_up_needed|info_only",
  "summary": "brief summary of email content",
  "suggested_response": "draft response Wesley could send"
}

Focus on medical device components like PCB assemblies, sensor modules, enclosures, cable assemblies, displays, etc."""

        # Call Claude API
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=system_prompt,
            messages=[{
                "role": "user", 
                "content": f"Analyze this supplier email:\n\n{email_content}"
            }]
        )
        
        # Parse Claude's response
        analysis_text = response.content[0].text
        
        # Try to extract JSON from response
        try:
            import re
            json_match = re.search(r'\{.*\}', analysis_text, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                # Fallback structured response if JSON parsing fails
                analysis = {
                    "supplier_name": "Unknown Supplier",
                    "email_type": "general",
                    "components": [],
                    "priority_level": "medium",
                    "action_required": "review_needed",
                    "summary": analysis_text[:200],
                    "suggested_response": "Thank you for your email. We are reviewing the information provided and will respond shortly."
                }
        except json.JSONDecodeError:
            # Final fallback
            analysis = {
                "supplier_name": "Unknown Supplier", 
                "email_type": "general",
                "components": [],
                "priority_level": "medium",
                "action_required": "review_needed", 
                "summary": analysis_text[:200],
                "suggested_response": "Thank you for your email. We are reviewing the information provided and will respond shortly."
            }
        
        return {
            "status": "success",
            "analysis": analysis,
            "raw_response": analysis_text
        }
        
    except Exception as e:
        print(f"Claude API error: {e}")
        raise HTTPException(status_code=500, detail=f"AI processing failed: {str(e)}")

@app.get("/suppliers", response_class=HTMLResponse)
async def suppliers_view(request: Request):
    """Supplier comparison dashboard"""
    return templates.TemplateResponse("suppliers.html", {
        "request": request,
        "suppliers": suppliers_data,
        "parsed_data": parsed_data
    })

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)