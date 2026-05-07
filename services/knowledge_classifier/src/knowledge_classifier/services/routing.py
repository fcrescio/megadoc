"""Routing service for choosing a scan processing pipeline."""

from enum import Enum

from pydantic import BaseModel, Field

from common.db.models import OCRResult


class PipelineFamily(str, Enum):
    """High-level families used by the scan router."""

    GENERAL = "general"
    NORMATIVE = "normative"
    MEETING = "meeting"
    FINANCIAL = "financial"
    UTILITY_VENDOR = "utility_vendor"
    TECHNICAL_ADMIN = "technical_admin"


class PipelineRoutingDecision(BaseModel):
    """Routing decision for a scan unit."""

    pipeline_id: str
    family: str
    confidence: float = Field(..., ge=0, le=1)
    rationale: str
    signals: list[str] = Field(default_factory=list)


class PipelineRouterService:
    """Choose the most appropriate pipeline family for a scan."""

    def route_scan(self, ocr_result: OCRResult) -> PipelineRoutingDecision:
        """Route a scan based on coarse document-family signals."""
        scan_text = self._scan_text(ocr_result)
        return self.route_text(scan_text)

    def route_text(self, text: str) -> PipelineRoutingDecision:
        """Route one document or segment based on coarse document-family signals."""
        scan_text = (text or "")[:30000].lower()
        compact_text = self._compact_scan_text(scan_text)

        for rule in (
            self._route_normative,
            self._route_meeting,
            self._route_financial,
            self._route_utility_vendor,
            self._route_technical_admin,
        ):
            decision = rule(scan_text, compact_text)
            if decision is not None:
                return decision

        return PipelineRoutingDecision(
            pipeline_id="general_pipeline",
            family=PipelineFamily.GENERAL.value,
            confidence=0.55,
            rationale="No specialized family produced a strong coarse routing signal.",
            signals=[],
        )

    def _scan_text(self, ocr_result: OCRResult) -> str:
        text = "\n".join(
            part
            for part in (
                ocr_result.markdown_text or "",
                ocr_result.full_text or "",
            )
            if part
        )
        return text[:30000].lower()

    def _compact_scan_text(self, scan_text: str) -> str:
        return "".join(ch for ch in scan_text if ch.isalnum())

    def _route_normative(
        self,
        scan_text: str,
        compact_text: str,
    ) -> PipelineRoutingDecision | None:
        signals = []
        if "regolamento" in scan_text:
            signals.append("regolamento")
        if "condominio" in scan_text:
            signals.append("condominio")
        article_markers = scan_text.count("art.") + scan_text.count("articolo")
        if article_markers >= 3:
            signals.append(f"article_markers:{article_markers}")
        if len(signals) < 3:
            return None
        return PipelineRoutingDecision(
            pipeline_id="normative_pipeline",
            family=PipelineFamily.NORMATIVE.value,
            confidence=0.9,
            rationale="The scan looks like a long-form normative/regulation document with recurring articles.",
            signals=signals,
        )

    def _route_meeting(
        self,
        scan_text: str,
        compact_text: str,
    ) -> PipelineRoutingDecision | None:
        signals = [
            token
            for token in ("verbale", "assemblea", "delibera", "presenti", "assenti")
            if token in scan_text
        ]
        if len(signals) < 2:
            return None
        return PipelineRoutingDecision(
            pipeline_id="meeting_pipeline",
            family=PipelineFamily.MEETING.value,
            confidence=0.82,
            rationale="The scan contains meeting/assembly language and is better handled as minutes or meeting material.",
            signals=signals,
        )

    def _route_financial(
        self,
        scan_text: str,
        compact_text: str,
    ) -> PipelineRoutingDecision | None:
        signals = []

        for token in (
            "rendiconto",
            "bilancio",
            "riparto",
            "spese",
            "consuntivo",
            "preventivo",
            "fattura",
            "imponibile",
            "importo fattura",
            "iva",
            "totale",
            "totale vendita",
            "totale articoli",
            "acconto",
            "saldo",
            "pagamento",
            "contanti",
            "cliente",
            "memoria di spesa",
            "ordine n",
            "ordine",
        ):
            if token in scan_text:
                signals.append(token)

        for label, token in (
            ("partita_iva", "partitaiva"),
            ("partita_va", "partitava"),
            ("cedente_prestatore", "cedenteoprestatore"),
            ("dati_cliente", "datiidentificatividelcliente"),
            ("codice_fiscale_partita_iva", "codicefiscalepartitaiva"),
            ("totale_vendita", "totalevendita"),
            ("totale_articoli", "totalearticoli"),
            ("memoria_di_spesa", "memoriadispesa"),
        ):
            if token in compact_text:
                signals.append(label)

        retail_brands = (
            "unieuro",
            "euronics",
            "mediaworld",
            "expert",
            "trony",
            "whirlpool",
            "indesit",
        )
        matched_brands = [brand for brand in retail_brands if brand in compact_text]
        if matched_brands:
            signals.extend(f"brand:{brand}" for brand in matched_brands)

        if len(signals) < 2:
            return None
        return PipelineRoutingDecision(
            pipeline_id="financial_pipeline",
            family=PipelineFamily.FINANCIAL.value,
            confidence=0.84,
            rationale="The scan contains accounting/budget language and is better routed to a financial pipeline.",
            signals=signals,
        )

    def _route_utility_vendor(
        self,
        scan_text: str,
        compact_text: str,
    ) -> PipelineRoutingDecision | None:
        signals = [
            token
            for token in ("fattura", "fornitura", "bolletta", "acque", "enel", "servizio idrico")
            if token in scan_text
        ]
        if len(signals) < 2:
            return None
        return PipelineRoutingDecision(
            pipeline_id="utility_vendor_pipeline",
            family=PipelineFamily.UTILITY_VENDOR.value,
            confidence=0.8,
            rationale="The scan looks like a utility/vendor contract, bill, or supply document.",
            signals=signals,
        )

    def _route_technical_admin(
        self,
        scan_text: str,
        compact_text: str,
    ) -> PipelineRoutingDecision | None:
        signals = [
            token
            for token in (
                "fine lavori",
                "comune di",
                "dia",
                "scia",
                "permesso di costruire",
                "agibilita",
                "agibilità",
            )
            if token in scan_text
        ]
        if len(signals) < 2:
            return None
        return PipelineRoutingDecision(
            pipeline_id="technical_admin_pipeline",
            family=PipelineFamily.TECHNICAL_ADMIN.value,
            confidence=0.82,
            rationale="The scan looks like a technical or administrative form tied to works or municipal procedures.",
            signals=signals,
        )
