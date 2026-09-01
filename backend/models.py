from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Union
from datetime import datetime
from enum import Enum
import uuid

# Enums
class UserType(str, Enum):
    CANDIDATE = "candidate"
    EMPLOYER = "employer"
    PARTNER = "partner"
    ADMIN = "admin"

class PartnerBillingMode(str, Enum):
    PER_CLICK = "per_click"
    PER_POSTING = "per_posting"

class JobType(str, Enum):
    CDI = "CDI"
    CDD = "CDD"
    STAGE = "Stage"
    FREELANCE = "Freelance"
    INTERIM = "Intérim"
    TITULAIRE = "Titulaire"

class ApplicationStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

# Base Models
class BaseDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# User Models
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    user_type: UserType = UserType.CANDIDATE
    phone: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    skills: List[str] = []
    experience_years: Optional[int] = None

class UserCreate(UserBase):
    password: str
    # Provenance (tracking à l'inscription) — optionnel
    signup_source: Optional[str] = None
    signup_referrer: Optional[str] = None
    signup_landing: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[List[str]] = None
    experience_years: Optional[int] = None
    profile_photo_url: Optional[str] = None
    social_link_1: Optional[str] = None
    social_link_2: Optional[str] = None
    social_link_3: Optional[str] = None

class User(BaseDocument, UserBase):
    hashed_password: str
    is_active: bool = True
    is_verified: bool = False
    profile_photo_url: Optional[str] = None
    social_link_1: Optional[str] = None
    social_link_2: Optional[str] = None
    social_link_3: Optional[str] = None

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    first_name: str
    last_name: str
    user_type: UserType
    phone: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    skills: List[str] = []
    experience_years: Optional[int] = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    profile_photo_url: Optional[str] = None
    social_link_1: Optional[str] = None
    social_link_2: Optional[str] = None
    social_link_3: Optional[str] = None

# Company Models
class CompanyBase(BaseModel):
    name: str
    description: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    logo_url: Optional[str] = None

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    logo_url: Optional[str] = None

class Company(BaseDocument, CompanyBase):
    owner_id: str  # User ID who owns/manages this company

# Job Models
class JobBase(BaseModel):
    title: str
    description: str
    company_id: str
    location: str
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "EUR"
    job_type: JobType = JobType.CDI
    is_remote: bool = False
    is_urgent: bool = False
    requirements: List[str] = []
    benefits: List[str] = []
    tags: List[str] = []

class JobCreate(JobBase):
    is_premium: bool = False  # P0-005 : offre Premium payante (consomme 1 crédit) sinon standard gratuite

class JobUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    job_type: Optional[JobType] = None
    is_remote: Optional[bool] = None
    is_urgent: Optional[bool] = None
    requirements: Optional[List[str]] = None
    benefits: Optional[List[str]] = None
    tags: Optional[List[str]] = None

class Job(BaseDocument, JobBase):
    employer_id: str  # User ID who posted the job
    is_active: bool = True
    is_premium: bool = False  # P0-005 : offre Premium (consommé 1 crédit recruteur)
    premium_granted_at: Optional[datetime] = None  # P0-005 : traçabilité de l'octroi premium
    views_count: int = 0
    applications_count: int = 0

class JobResponse(BaseModel):
    id: str
    title: str
    description: str
    company: dict  # Company info will be populated
    location: str
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str
    job_type: JobType
    is_remote: bool
    is_urgent: bool
    requirements: List[str]
    benefits: List[str]
    tags: List[str]
    is_active: bool
    is_premium: bool = False  # P0-005
    views_count: int
    applications_count: int
    created_at: datetime
    is_new: bool = False  # Computed field for jobs less than 7 days old
    is_partner: bool = False
    external_url: Optional[str] = None
    cpc: Optional[float] = None
    logo_url: Optional[str] = None

# Application Models
class ApplicationBase(BaseModel):
    job_id: str
    cover_letter: Optional[str] = None
    cv_url: Optional[str] = None

class ApplicationCreate(ApplicationBase):
    pass

class Application(BaseDocument, ApplicationBase):
    candidate_id: str  # User ID of the candidate
    status: ApplicationStatus = ApplicationStatus.PENDING
    employer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None

class ApplicationResponse(BaseModel):
    id: str
    job: dict  # Job info will be populated
    candidate: dict  # Candidate info will be populated (for employers)
    cover_letter: Optional[str]
    cv_url: Optional[str]
    status: ApplicationStatus
    employer_notes: Optional[str]
    created_at: datetime
    reviewed_at: Optional[datetime]

# Saved Job Models
class SavedJob(BaseDocument):
    user_id: str
    job_id: str

# Job Alert / Saved Search Models
class AlertFrequency(str, Enum):
    INSTANT = "instant"
    DAILY = "daily"
    WEEKLY = "weekly"
    NEVER = "never"

class JobAlertCreate(BaseModel):
    name: Optional[str] = None
    search: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[JobType] = None
    is_remote: Optional[bool] = None
    salary_min: Optional[int] = None
    frequency: AlertFrequency = AlertFrequency.DAILY

class JobAlertUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[AlertFrequency] = None
    is_active: Optional[bool] = None

class JobAlert(BaseDocument):
    user_id: str
    name: str
    search: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[JobType] = None
    is_remote: Optional[bool] = None
    salary_min: Optional[int] = None
    frequency: AlertFrequency = AlertFrequency.DAILY
    is_active: bool = True
    last_sent_at: Optional[datetime] = None

class JobAlertResponse(BaseModel):
    id: str
    name: str
    search: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[JobType] = None
    is_remote: Optional[bool] = None
    salary_min: Optional[int] = None
    frequency: AlertFrequency
    is_active: bool
    last_sent_at: Optional[datetime] = None
    created_at: datetime

# Auth Models
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    email: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    expected_user_type: Optional[str] = None  # candidate | employer | partner | admin — if set, must match account type

class LoginResponse(BaseModel):
    user: UserResponse
    token: Token

# Search Models
class PartnerCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str = ""
    company_name: str
    billing_mode: PartnerBillingMode = PartnerBillingMode.PER_CLICK
    default_cpc: float = 0.0          # € per click (fallback if not in XML)
    posting_price: float = 0.0        # € per annonce (per_posting mode)
    xml_feed_url: Optional[str] = None

class PartnerConfigUpdate(BaseModel):
    company_name: Optional[str] = None
    billing_mode: Optional[PartnerBillingMode] = None
    default_cpc: Optional[float] = None
    posting_price: Optional[float] = None
    xml_feed_url: Optional[str] = None
    add_pack: Optional[int] = None    # add N annonces credits (5/10/20/50/100/200)
    add_balance: Optional[float] = None  # add € credit balance
    is_active: Optional[bool] = None

class PartnerProfile(BaseDocument):
    user_id: str
    company_name: str
    billing_mode: PartnerBillingMode = PartnerBillingMode.PER_CLICK
    default_cpc: float = 0.0
    posting_price: float = 0.0
    xml_feed_url: Optional[str] = None
    logo_url: Optional[str] = None
    postings_remaining: int = 0       # annonces credits left (per_posting)
    balance: float = 0.0              # € prepaid balance (per_click)
    total_clicks: int = 0
    total_spent: float = 0.0
    is_active: bool = True

class AdminUserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None

# Search Models
class JobSearchQuery(BaseModel):
    search: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[JobType] = None
    is_remote: Optional[bool] = None
    salary_min: Optional[int] = None
    company_id: Optional[str] = None
    page: int = 1
    limit: int = 20
    sort: str = "created_at"  # created_at, salary_min, title

class JobSearchResponse(BaseModel):
    jobs: List[JobResponse]
    total: int
    page: int
    limit: int
    total_pages: int