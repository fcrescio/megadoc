from common.db.models import OCRResult
from knowledge_classifier.services.routing import PipelineRouterService


def _ocr(markdown_text: str) -> OCRResult:
    return OCRResult(
        document_id="00000000-0000-0000-0000-000000000001",
        document_version_id="00000000-0000-0000-0000-000000000002",
        engine_name="docling",
        engine_version="test",
        pipeline_version="test",
        status="succeeded",
        full_text=markdown_text,
        markdown_text=markdown_text,
        structured_json={},
        page_count=1,
    )


def test_router_routes_regulation_scans_to_normative_pipeline():
    service = PipelineRouterService()
    ocr_result = _ocr(
        "Regolamento del condominio. Art. 1 proprietà comune. "
        "Art. 2 assemblea. Articolo 3 innovazioni. Articolo 4 amministratore."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "normative_pipeline"
    assert decision.family == "normative"


def test_router_routes_financial_scans_to_financial_pipeline():
    service = PipelineRouterService()
    ocr_result = _ocr(
        "Bilancio consuntivo del condominio. Rendiconto gestione 2024. "
        "Riparto spese e preventivo 2025."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_routes_invoice_scans_to_financial_pipeline():
    service = PipelineRouterService()
    ocr_result = _ocr(
        "FATTURA n.13. Imponibile, iva 20%, importo fattura, totale documento."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_routes_noisy_invoice_ocr_to_financial_pipeline():
    service = PipelineRouterService()
    ocr_result = _ocr(
        "DATIIDENTIFICATIVIDELCLIENTE PartitaVA01735100503 "
        "CEDENTEOPRESTATOREDOMICILIORESIDENZACODICEFSCALEPARTITAIVA"
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_falls_back_to_general_pipeline_for_unknown_scans():
    service = PipelineRouterService()
    ocr_result = _ocr("Testo eterogeneo senza segnali forti e senza famiglia specializzata evidente.")

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "general_pipeline"
    assert decision.family == "general"
