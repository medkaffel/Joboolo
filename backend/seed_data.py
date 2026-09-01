from database import get_database
from models import Job, Company, User, UserType, JobType
from auth import get_password_hash
from config import ensure_seeding_allowed
import asyncio
from datetime import datetime, timedelta
import uuid

async def seed_companies():
    """Seed companies data"""
    db = await get_database()
    
    companies_data = [
        {
            "_id": "comp_1",
            "name": "TechCorp France",
            "description": "Leader français des solutions technologiques innovantes",
            "industry": "Technologie",
            "size": "100-500 employés",
            "website": "https://techcorp.fr",
            "location": "Paris",
            "owner_id": "emp_1",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_2", 
            "name": "DigitalBoost",
            "description": "Agence de marketing digital en pleine expansion",
            "industry": "Marketing Digital",
            "size": "50-100 employés",
            "website": "https://digitalboost.fr",
            "location": "Lyon",
            "owner_id": "emp_2",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_3",
            "name": "Hôpital Saint-Antoine",
            "description": "Établissement hospitalier public",
            "industry": "Santé",
            "size": "500+ employés",
            "location": "Marseille",
            "owner_id": "emp_3",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_4",
            "name": "SoftSales Pro",
            "description": "Solutions commerciales pour l'IT",
            "industry": "Vente/IT",
            "size": "20-50 employés",
            "location": "Toulouse",
            "owner_id": "emp_4",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_5",
            "name": "Cabinet Expertise Plus",
            "description": "Cabinet d'expertise comptable",
            "industry": "Comptabilité",
            "size": "10-20 employés",
            "location": "Nantes",
            "owner_id": "emp_5",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_6",
            "name": "MediaCom Agency",
            "description": "Agence de communication créative",
            "industry": "Communication",
            "size": "20-50 employés",
            "location": "Bordeaux",
            "owner_id": "emp_6",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_7",
            "name": "DataInsights",
            "description": "Analyse de données et business intelligence",
            "industry": "Data Science",
            "size": "50-100 employés",
            "location": "Paris",
            "owner_id": "emp_7",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "comp_8",
            "name": "Éducation Nationale",
            "description": "Ministère de l'Éducation Nationale",
            "industry": "Éducation",
            "size": "500+ employés",
            "location": "Nice",
            "owner_id": "emp_8",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
    ]
    
    # Idempotent upsert: keep user-created companies, only add missing seed ones
    for company in companies_data:
        await db.companies.update_one(
            {"_id": company["_id"]},
            {"$setOnInsert": company},
            upsert=True,
        )
    print(f"Seeded/ensured {len(companies_data)} companies")

async def seed_users():
    """Seed users data"""
    db = await get_database()
    
    users_data = [
        # Employers
        {
            "_id": "emp_1",
            "email": "recruteur@techcorp.fr",
            "first_name": "Marie",
            "last_name": "Dubois",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Paris",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_2",
            "email": "hr@digitalboost.fr",
            "first_name": "Pierre",
            "last_name": "Martin",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Lyon",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_3",
            "email": "rh@hopital-antoine.fr",
            "first_name": "Sophie",
            "last_name": "Bernard",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Marseille",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_4",
            "email": "recrutement@softsales.fr",
            "first_name": "Thomas",
            "last_name": "Leroy",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Toulouse",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_5",
            "email": "contact@expertise-plus.fr",
            "first_name": "Julie",
            "last_name": "Moreau",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Nantes",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_6",
            "email": "rh@mediacom.fr",
            "first_name": "Antoine",
            "last_name": "Petit",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Bordeaux",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_7",
            "email": "jobs@datainsights.fr",
            "first_name": "Camille",
            "last_name": "Rousseau",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Paris",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        {
            "_id": "emp_8",
            "email": "recrutement@education.gouv.fr",
            "first_name": "Laurent",
            "last_name": "Garcia",
            "user_type": UserType.EMPLOYER,
            "hashed_password": get_password_hash("password123"),
            "location": "Nice",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        },
        # Test candidate
        {
            "_id": "cand_1",
            "email": "candidate@test.fr",
            "first_name": "Jean",
            "last_name": "Dupont",
            "user_type": UserType.CANDIDATE,
            "hashed_password": get_password_hash("password123"),
            "location": "Paris",
            "bio": "Développeur full stack passionné",
            "skills": ["JavaScript", "React", "Node.js", "Python"],
            "experience_years": 3,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
    ]
    
    # Idempotent upsert: never delete registered users, only add missing seed ones
    for user in users_data:
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$setOnInsert": user},
            upsert=True,
        )
    print(f"Seeded/ensured {len(users_data)} users")

async def seed_jobs():
    """Seed jobs data based on mock data"""
    db = await get_database()
    
    # Calculate dates for "new" jobs
    now = datetime.utcnow()
    
    jobs_data = [
        {
            "_id": "job_1",
            "title": "Développeur Full Stack React/Node.js",
            "description": "Nous recherchons un développeur full stack expérimenté pour rejoindre notre équipe de développement. Vous travaillerez sur des projets innovants utilisant React, Node.js et MongoDB. Expérience requise : 3+ ans en développement web, maîtrise de JavaScript ES6+, connaissance de Git.",
            "company_id": "comp_1",
            "employer_id": "emp_1",
            "location": "Paris (75)",
            "salary_min": 45000,
            "salary_max": 55000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": False,
            "is_urgent": False,
            "requirements": ["3+ ans d'expérience", "JavaScript ES6+", "React", "Node.js", "Git"],
            "benefits": ["Télétravail partiel", "Formation continue", "Tickets restaurant"],
            "tags": ["développement", "fullstack", "react", "nodejs"],
            "is_active": True,
            "views_count": 45,
            "applications_count": 12,
            "created_at": now - timedelta(days=2),
            "updated_at": now - timedelta(days=2)
        },
        {
            "_id": "job_2",
            "title": "Chef de Projet Marketing Digital",
            "description": "Rejoignez notre agence de marketing digital en pleine croissance ! Vous serez responsable de la gestion de projets clients, de la stratégie digitale et de l'animation d'équipe. Profil recherché : formation marketing/communication, 2+ ans d'expérience en digital.",
            "company_id": "comp_2",
            "employer_id": "emp_2",
            "location": "Lyon (69)",
            "salary_min": 38000,
            "salary_max": 48000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": False,
            "is_urgent": True,
            "requirements": ["Formation marketing/communication", "2+ ans d'expérience", "Leadership"],
            "benefits": ["Mutuelle", "CE", "Bonus performance"],
            "tags": ["marketing", "digital", "chef de projet", "communication"],
            "is_active": True,
            "views_count": 78,
            "applications_count": 23,
            "created_at": now - timedelta(days=1),
            "updated_at": now - timedelta(days=1)
        },
        {
            "_id": "job_3",
            "title": "Infirmier(ère) Diplômé(e) d'État",
            "description": "L'hôpital Saint-Antoine recrute des infirmiers DE pour ses services de médecine générale. Vous assurerez les soins infirmiers auprès des patients hospitalisés. Diplôme d'État d'infirmier requis, expérience en milieu hospitalier appréciée.",
            "company_id": "comp_3",
            "employer_id": "emp_3",
            "location": "Marseille (13)",
            "salary_min": 32000,
            "salary_max": 38000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": False,
            "is_urgent": True,
            "requirements": ["Diplôme d'État d'infirmier", "Expérience hospitalière appréciée"],
            "benefits": ["Sécurité sociale", "Retraite fonction publique", "Formation continue"],
            "tags": ["santé", "infirmier", "hôpital", "soins"],
            "is_active": True,
            "views_count": 156,
            "applications_count": 34,
            "created_at": now - timedelta(days=3),
            "updated_at": now - timedelta(days=3)
        },
        {
            "_id": "job_4",
            "title": "Commercial B2B - Secteur IT",
            "description": "Développez un portefeuille clients dans le secteur IT ! Vous prospecterez, négocierez et fidéliserez les entreprises. Formation commerciale souhaitée, goût pour les nouvelles technologies, permis B indispensable.",
            "company_id": "comp_4",
            "employer_id": "emp_4",
            "location": "Toulouse (31)",
            "salary_min": 35000,
            "salary_max": 50000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": False,
            "is_urgent": False,
            "requirements": ["Formation commerciale", "Permis B", "Goût pour les technologies"],
            "benefits": ["Commissions attractives", "Véhicule de fonction", "Frais remboursés"],
            "tags": ["commercial", "b2b", "it", "vente"],
            "is_active": True,
            "views_count": 89,
            "applications_count": 18,
            "created_at": now - timedelta(days=1),
            "updated_at": now - timedelta(days=1)
        },
        {
            "_id": "job_5",
            "title": "Comptable Général",
            "description": "Cabinet d'expertise comptable recherche un comptable général pour sa clientèle PME. Missions : tenue comptable, établissement des comptes annuels, relations clients. BTS/DUT comptabilité requis, maîtrise des logiciels comptables.",
            "company_id": "comp_5",
            "employer_id": "emp_5",
            "location": "Nantes (44)",
            "salary_min": 30000,
            "salary_max": 40000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": False,
            "is_urgent": False,
            "requirements": ["BTS/DUT comptabilité", "Logiciels comptables", "Relation client"],
            "benefits": ["Formation", "Mutuelle", "RTT"],
            "tags": ["comptabilité", "expertise comptable", "pme"],
            "is_active": True,
            "views_count": 67,
            "applications_count": 15,
            "created_at": now - timedelta(days=4),
            "updated_at": now - timedelta(days=4)
        },
        {
            "_id": "job_6",
            "title": "Chargé(e) de Communication",
            "description": "Agence de communication recrute un chargé de communication pour gérer les campagnes clients. Création de contenus, gestion des réseaux sociaux, relations presse. Formation communication, créativité et rigueur indispensables.",
            "company_id": "comp_6",
            "employer_id": "emp_6",
            "location": "Bordeaux (33)",
            "salary_min": 28000,
            "salary_max": 35000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": False,
            "is_urgent": False,
            "requirements": ["Formation communication", "Créativité", "Réseaux sociaux"],
            "benefits": ["Environnement créatif", "Flexibilité", "Projets variés"],
            "tags": ["communication", "réseaux sociaux", "créativité"],
            "is_active": True,
            "views_count": 92,
            "applications_count": 21,
            "created_at": now - timedelta(days=5),
            "updated_at": now - timedelta(days=5)
        },
        {
            "_id": "job_7",
            "title": "Data Analyst",
            "description": "Analysez et valorisez les données de nos clients ! Création de tableaux de bord, analyses statistiques, recommandations business. Maîtrise de SQL, Python/R, outils de visualisation (Tableau, Power BI). Formation analytique requise.",
            "company_id": "comp_7",
            "employer_id": "emp_7",
            "location": "Paris (75)",
            "salary_min": 40000,
            "salary_max": 50000,
            "salary_currency": "EUR",
            "job_type": JobType.CDI,
            "is_remote": True,
            "is_urgent": False,
            "requirements": ["SQL", "Python/R", "Tableau/Power BI", "Formation analytique"],
            "benefits": ["Télétravail complet", "Matériel fourni", "Formation data"],
            "tags": ["data", "analyse", "sql", "python", "bi"],
            "is_active": True,
            "views_count": 134,
            "applications_count": 28,
            "created_at": now - timedelta(days=2),
            "updated_at": now - timedelta(days=2)
        },
        {
            "_id": "job_8",
            "title": "Professeur des Écoles",
            "description": "Poste de professeur des écoles en élémentaire. Enseignement polyvalent du CP au CM2, suivi pédagogique des élèves, collaboration avec l'équipe éducative. Concours CRPE requis, expérience avec les enfants appréciée.",
            "company_id": "comp_8",
            "employer_id": "emp_8",
            "location": "Nice (06)",
            "salary_min": 25000,
            "salary_max": 30000,
            "salary_currency": "EUR",
            "job_type": JobType.TITULAIRE,
            "is_remote": False,
            "is_urgent": True,
            "requirements": ["Concours CRPE", "Expérience avec enfants appréciée"],
            "benefits": ["Sécurité de l'emploi", "Vacances scolaires", "Formation continue"],
            "tags": ["enseignement", "éducation", "enfants", "école"],
            "is_active": True,
            "views_count": 203,
            "applications_count": 45,
            "created_at": now - timedelta(days=7),
            "updated_at": now - timedelta(days=7)
        }
    ]
    
    # Idempotent upsert: keep employer-posted jobs, only add missing seed ones
    for job in jobs_data:
        await db.jobs.update_one(
            {"_id": job["_id"]},
            {"$setOnInsert": job},
            upsert=True,
        )
    print(f"Seeded/ensured {len(jobs_data)} jobs")

async def seed_database():
    """Seed all data (explicit dev/test only; refused in production)."""
    ensure_seeding_allowed()
    print("Starting database seeding...")
    await seed_companies()
    await seed_users()
    await seed_jobs()
    print("Database seeding completed!")

if __name__ == "__main__":
    asyncio.run(seed_database())