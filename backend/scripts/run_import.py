#!/usr/bin/env python3
"""
Script d'execution de l'import Monster.fr
Lance l'import des emplois depuis Monster.fr
"""

import asyncio
import sys
import os

# Ajouter le répertoire backend au path
sys.path.append('/app/backend')

from monster_scraper import MonsterJobScraper

async def main():
    print("=" * 60)
    print("🔄 JOBOOLO - IMPORT D'EMPLOIS DEPUIS MONSTER.FR")
    print("=" * 60)
    
    scraper = MonsterJobScraper()
    
    try:
        # Import 20 nouvelles offres d'emploi
        print("📥 Lancement de l'import de 20 offres d'emploi...")
        imported_count = await scraper.run_import(max_jobs=20)
        
        print("\n" + "=" * 60)
        if imported_count > 0:
            print(f"✅ SUCCÈS: {imported_count} nouvelles offres importées!")
            print("🎯 Les emplois sont maintenant disponibles sur Joboolo")
            print("💼 Les candidats peuvent maintenant postuler")
        else:
            print("ℹ️ Aucune nouvelle offre à importer (toutes existent déjà)")
        
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n⚠️ Import interrompu par l'utilisateur")
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())