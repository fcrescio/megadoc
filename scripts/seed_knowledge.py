"""Seed script for knowledge classifier data."""

import uuid
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from common.db.models import DocumentType, Topic


def seed_document_types(session):
    """Seed document types."""
    types_data = [
        {
            "code": "bolletta",
            "name": "Bolletta",
            "description": "Utility bills, service charges, payment notices",
            "parent_code": None,
        },
        {
            "code": "verbale_assemblea",
            "name": "Verbale Assemblea",
            "description": "Meeting minutes, assembly records, deliberations",
            "parent_code": None,
        },
        {
            "code": "regolamento_condominiale",
            "name": "Regolamento Condominiale",
            "description": "Condominium regulations, articles, internal rules and common property rules",
            "parent_code": None,
        },
        {
            "code": "rendiconto_contabile",
            "name": "Rendiconto Contabile",
            "description": "Financial statements, accounting reports",
            "parent_code": None,
        },
        {
            "code": "riparto_spese",
            "name": "Riparto Spese",
            "description": "Expense allocation documents",
            "parent_code": None,
        },
        {
            "code": "fattura",
            "name": "Fattura",
            "description": "Invoices from vendors and suppliers",
            "parent_code": None,
        },
        {
            "code": "preventivo",
            "name": "Preventivo",
            "description": "Quotes, estimates, price proposals",
            "parent_code": None,
        },
        {
            "code": "lettera",
            "name": "Lettera",
            "description": "Letters, correspondence, communications",
            "parent_code": None,
        },
        {
            "code": "contratto",
            "name": "Contratto",
            "description": "Contracts, agreements, legal documents",
            "parent_code": None,
        },
        {
            "code": "allegato_tecnico",
            "name": "Allegato Tecnico",
            "description": "Technical attachments, specifications, drawings",
            "parent_code": None,
        },
        {
            "code": "altro",
            "name": "Altro",
            "description": "Other documents not fitting standard categories",
            "parent_code": None,
        },
    ]
    
    for type_data in types_data:
        existing = session.execute(
            text("SELECT id FROM document_types WHERE code = :code"),
            {"code": type_data["code"]},
        ).first()
        if existing:
            session.execute(
                text(
                    """
                    UPDATE document_types
                    SET name = :name,
                        description = :description,
                        parent_code = :parent_code,
                        is_active = true
                    WHERE code = :code
                    """
                ),
                type_data,
            )
            print(f"Updated document type: {type_data['code']}")
            continue
        doc_type = DocumentType(
            id=uuid.uuid4(),
            code=type_data["code"],
            name=type_data["name"],
            description=type_data["description"],
            parent_code=type_data["parent_code"],
            is_active=True,
            created_at=datetime.utcnow(),
        )
        session.add(doc_type)
        print(f"Created document type: {type_data['code']}")


def seed_topics(session):
    """Seed example topics."""
    topics_data = [
        {
            "slug": "condominio_via_roma_bilancio_2024",
            "title": "Condominio Via Roma - Bilancio 2024",
            "topic_class": "financial_period",
            "description": "Financial documents for Condominio Via Roma fiscal year 2024",
        },
        {
            "slug": "rifacimento_facciata",
            "title": "Rifacimento Facciata",
            "topic_class": "building_issue",
            "description": "Documents related to facade renovation project",
        },
        {
            "slug": "fornitura_energia",
            "title": "Fornitura Energia Elettrica",
            "topic_class": "vendor_relationship",
            "description": "Energy supplier contracts and invoices",
        },
        {
            "slug": "assemblea_straordinaria_2024_03_12",
            "title": "Assemblea Straordinaria 12 Marzo 2024",
            "topic_class": "meeting",
            "description": "Extraordinary assembly meeting on March 12, 2024",
        },
        {
            "slug": "pratica_legale_rossi",
            "title": "Pratica Legale Rossi",
            "topic_class": "legal_matter",
            "description": "Legal matter involving Rossi",
        },
        {
            "slug": "manutenzione_ascensore",
            "title": "Manutenzione Ascensore",
            "topic_class": "building_issue",
            "description": "Elevator maintenance contracts and service records",
        },
    ]
    
    for topic_data in topics_data:
        topic = Topic(
            id=uuid.uuid4(),
            slug=topic_data["slug"],
            title=topic_data["title"],
            topic_class=topic_data["topic_class"],
            description=topic_data["description"],
            canonical=True,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        session.add(topic)
        print(f"Created topic: {topic_data['slug']}")


def main():
    """Run seed script."""
    database_url = "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"
    
    engine = create_engine(database_url)
    
    with Session(engine) as session:
        seed_document_types(session)
        session.flush()
        
        result = session.execute(text("SELECT COUNT(*) FROM topics"))
        count = result.scalar()
        
        if count and count > 0:
            print(f"Topics already exist ({count} records). Skipping seed.")
        else:
            seed_topics(session)
            session.flush()
        
        session.commit()
        print("Seed completed successfully!")


if __name__ == "__main__":
    main()
