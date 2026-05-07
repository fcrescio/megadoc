from common.db.models import OCRResult
from knowledge_classifier.llm.mock import MockDeterministicProvider
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
    service = PipelineRouterService(MockDeterministicProvider())
    ocr_result = _ocr(
        "Regolamento del condominio. Art. 1 proprietà comune. "
        "Art. 2 assemblea. Articolo 3 innovazioni. Articolo 4 amministratore."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "normative_pipeline"
    assert decision.family == "normative"


def test_router_routes_financial_scans_to_financial_pipeline():
    service = PipelineRouterService(MockDeterministicProvider())
    ocr_result = _ocr(
        "Bilancio consuntivo del condominio. Rendiconto gestione 2024. "
        "Riparto spese e preventivo 2025."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_routes_invoice_scans_to_financial_pipeline():
    service = PipelineRouterService(MockDeterministicProvider())
    ocr_result = _ocr(
        "FATTURA n.13. Imponibile, iva 20%, importo fattura, totale documento."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_routes_noisy_invoice_ocr_to_financial_pipeline():
    service = PipelineRouterService(MockDeterministicProvider())
    ocr_result = _ocr(
        "DATIIDENTIFICATIVIDELCLIENTE PartitaVA01735100503 "
        "CEDENTEOPRESTATOREDOMICILIORESIDENZACODICEFSCALEPARTITAIVA"
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_routes_retail_receipt_to_financial_pipeline():
    service = PipelineRouterService(MockDeterministicProvider())
    ocr_result = _ocr(
        "UNIEURO S.P.A. Totale vendita 445,00. Acconto 400,00. "
        "Cliente Crescioli Francesco. Pagamento contanti. Memoria di spesa."
    )

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "financial_pipeline"
    assert decision.family == "financial"


def test_router_falls_back_to_general_pipeline_for_unknown_scans():
    service = PipelineRouterService(MockDeterministicProvider())
    ocr_result = _ocr("Testo eterogeneo senza segnali forti e senza famiglia specializzata evidente.")

    decision = service.route_scan(ocr_result)

    assert decision.pipeline_id == "general_pipeline"
    assert decision.family == "general"


def test_router_can_route_individual_segment_texts_independently():
    service = PipelineRouterService(MockDeterministicProvider())

    accounting_decision = service.route_text(
        "Bilancio consuntivo. Rendiconto gestione 2024. Riparto spese."
    )
    utility_decision = service.route_text(
        "Fattura servizio idrico. Bolletta Acque per fornitura acqua."
    )

    assert accounting_decision.pipeline_id == "financial_pipeline"
    assert utility_decision.pipeline_id == "utility_vendor_pipeline"
