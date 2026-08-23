from fastapi import APIRouter, HTTPException, Depends
from typing import List
from models import (
    Company, CompanyCreate, CompanyUpdate, User
)
from database import get_database
from auth import get_current_active_user, require_employer
from datetime import datetime

router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("", response_model=List[Company])
async def get_companies():
    """Get all companies"""
    db = await get_database()
    
    cursor = db.companies.find({}).sort([("name", 1)])
    companies_docs = await cursor.to_list(length=100)
    
    companies = [Company(**company_doc) for company_doc in companies_docs]
    return companies

@router.get("/{company_id}", response_model=Company)
async def get_company(company_id: str):
    """Get a specific company"""
    db = await get_database()
    
    company_doc = await db.companies.find_one({"_id": company_id})
    if not company_doc:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return Company(**company_doc)

@router.post("", response_model=Company)
async def create_company(
    company_data: CompanyCreate,
    current_user: User = Depends(require_employer)
):
    """Create a new company (employers only)"""
    db = await get_database()
    
    # Check if company name already exists
    existing_company = await db.companies.find_one({"name": company_data.name})
    if existing_company:
        raise HTTPException(
            status_code=400,
            detail="Company with this name already exists"
        )
    
    # Create company document
    company_doc = {
        "_id": f"comp_{datetime.utcnow().timestamp()}",
        **company_data.dict(),
        "owner_id": current_user.id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    # Insert company
    await db.companies.insert_one(company_doc)
    
    return Company(**company_doc)

@router.put("/{company_id}", response_model=Company)
async def update_company(
    company_id: str,
    company_data: CompanyUpdate,
    current_user: User = Depends(require_employer)
):
    """Update a company (owner only)"""
    db = await get_database()
    
    # Check if company exists and belongs to user
    company = await db.companies.find_one({
        "_id": company_id,
        "owner_id": current_user.id
    })
    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found or you don't have permission to edit it"
        )
    
    # Update company
    update_data = {k: v for k, v in company_data.dict().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()
    
    await db.companies.update_one(
        {"_id": company_id},
        {"$set": update_data}
    )
    
    # Get updated company
    updated_company = await db.companies.find_one({"_id": company_id})
    return Company(**updated_company)

@router.get("/user/my-companies", response_model=List[Company])
async def get_my_companies(current_user: User = Depends(require_employer)):
    """Get companies owned by current user"""
    db = await get_database()
    
    cursor = db.companies.find({"owner_id": current_user.id}).sort([("name", 1)])
    companies_docs = await cursor.to_list(length=100)
    
    companies = [Company(**company_doc) for company_doc in companies_docs]
    return companies