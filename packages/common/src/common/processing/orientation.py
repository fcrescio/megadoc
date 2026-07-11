from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from common.config import Settings, get_settings
from common.processing.preflight import PDFPreflightReport

logger = logging.getLogger(__name__)


@dataclass
class OrientationPreprocessResult:
    normalized_path: Path | None
    metadata: dict


class OrientationPreprocessService:
    _classifier = None
    _classifier_model_id: str | None = None
    _warmup_lock_path = Path("/tmp/megadoc-paddle-orientation-init.lock")
    _warmup_ready_prefix = "megadoc-paddle-orientation-init"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def preprocess(self, source: Path, preflight: PDFPreflightReport | None = None) -> OrientationPreprocessResult | None:
        backend = self._settings.rotation_detector_backend.strip().lower()
        if backend in {"", "none", "disabled"}:
            return None
        if backend != "paddle_doc_orientation":
            return OrientationPreprocessResult(
                normalized_path=None,
                metadata={
                    "backend": backend,
                    "applied": False,
                    "reason": "unsupported_backend",
                },
            )
        if preflight and preflight.dominant_declared_rotation not in {None, 0}:
            return OrientationPreprocessResult(
                normalized_path=None,
                metadata={
                    "backend": backend,
                    "applied": False,
                    "reason": "declared_rotation_present",
                    "declared_rotation": preflight.dominant_declared_rotation,
                },
            )

        detections = self._detect_page_orientations(source, preflight)
        if not detections:
            return OrientationPreprocessResult(
                normalized_path=None,
                metadata={"backend": backend, "applied": False, "reason": "no_detections"},
            )

        page_count = preflight.page_count if preflight and preflight.page_count else max(
            (item["page_number"] for item in detections), default=1
        )
        qualified = self._qualified_detections(detections)
        sampled_rotations = {int(item["rotation"]) % 360 for item in qualified}
        full_page_detection = len(detections) >= page_count
        if len(sampled_rotations) > 1 and not full_page_detection:
            detections = self._detect_page_orientations(
                source, preflight, page_numbers=list(range(1, page_count + 1))
            )
            qualified = self._qualified_detections(detections)
            full_page_detection = len(detections) >= page_count

        dominant_rotation = self._choose_rotation(detections)
        if dominant_rotation is None and not full_page_detection:
            return OrientationPreprocessResult(
                normalized_path=None,
                metadata={
                    "backend": backend,
                    "applied": False,
                    "reason": "insufficient_consensus",
                    "detections": detections,
                },
            )

        detected_by_page = {
            int(item["page_number"]): int(item["rotation"]) % 360
            for item in qualified
        }
        fallback_rotation = dominant_rotation or 0
        page_rotations = {
            page_number: detected_by_page.get(page_number, fallback_rotation)
            for page_number in range(1, page_count + 1)
        }
        inferred_pages = sorted(
            page_number for page_number in range(1, page_count + 1)
            if page_number not in detected_by_page
        )
        review_pages = inferred_pages if full_page_detection else []
        mixed_orientation = len(set(page_rotations.values())) > 1
        reverse_page_order = self._should_reverse_page_order(
            dominant_rotation or 0, detections
        ) and not mixed_orientation and not review_pages
        normalized_path = self._rotate_pdf(
            source,
            dominant_rotation or 0,
            page_rotations=page_rotations,
            reverse_page_order=reverse_page_order,
        )
        return OrientationPreprocessResult(
            normalized_path=normalized_path,
            metadata={
                "backend": backend,
                "applied": True,
                "rotation_applied": dominant_rotation,
                "page_rotations": {str(key): value for key, value in page_rotations.items()},
                "mixed_orientation": mixed_orientation,
                "full_page_detection": full_page_detection,
                "inferred_pages": [] if full_page_detection else inferred_pages,
                "review_pages": review_pages,
                "page_order_reversed": reverse_page_order,
                "detections": detections,
            },
        )

    def _detect_page_orientations(
        self,
        source: Path,
        preflight: PDFPreflightReport | None,
        page_numbers: list[int] | None = None,
    ) -> list[dict]:
        try:
            import fitz
        except ImportError:
            logger.warning("orientation_preprocess_missing_pymupdf")
            return []
        classifier = self._get_classifier()
        if classifier is None:
            return []

        document = fitz.open(source)
        try:
            sample_pages = page_numbers or self._sample_page_numbers(document.page_count)
            detections: list[dict] = []
            with TemporaryDirectory(prefix="megadoc-rot-") as temp_dir:
                temp_root = Path(temp_dir)
                for page_number in sample_pages:
                    page = document.load_page(page_number - 1)
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                    image_path = temp_root / f"page-{page_number}.png"
                    pixmap.save(str(image_path))
                    prediction = self._predict_orientation(classifier, image_path)
                    if prediction is None:
                        continue
                    detections.append(
                        {
                            "page_number": page_number,
                            "rotation": prediction["rotation"],
                            "confidence": prediction["confidence"],
                        }
                    )
            return detections
        finally:
            document.close()

    def _predict_orientation(self, classifier, image_path: Path) -> dict | None:
        try:
            output = classifier.predict(str(image_path), batch_size=1)
        except TypeError:
            output = classifier.predict(str(image_path))
        try:
            result = next(iter(output))
        except TypeError:
            result = output

        payload = result
        result_res = getattr(result, "res", None)
        if isinstance(result_res, dict):
            payload = result_res
        elif isinstance(result, dict):
            payload = result
        else:
            payload = {}

        labels = payload.get("label_names") or []
        scores = payload.get("scores")
        if not labels:
            return None
        label = str(labels[0])
        try:
            rotation = int(label)
        except ValueError:
            return None
        confidence = 0.0
        if scores is not None:
            try:
                first_score = scores[0]
                if hasattr(first_score, "item"):
                    first_score = first_score.item()
                confidence = float(first_score)
            except Exception:
                confidence = 0.0
        return {
            "rotation": rotation % 360,
            "confidence": confidence,
        }

    def _get_classifier(self):
        model_name = self._settings.rotation_detector_model_id or "PP-LCNet_x1_0_doc_ori"
        if self._classifier is not None and self._classifier_model_id == model_name:
            return self._classifier

        try:
            from paddleocr import DocImgOrientationClassification
        except ImportError:
            logger.warning("orientation_preprocess_missing_paddleocr")
            return None

        ready_path = Path(f"/tmp/{self._warmup_ready_prefix}-{self._sanitize_model_name(model_name)}.ready")
        if ready_path.exists():
            self._classifier = DocImgOrientationClassification(model_name=model_name)
            self._classifier_model_id = model_name
            return self._classifier

        with self._warmup_lock():
            if ready_path.exists():
                self._classifier = DocImgOrientationClassification(model_name=model_name)
                self._classifier_model_id = model_name
                return self._classifier

            classifier = DocImgOrientationClassification(model_name=model_name)
            ready_path.touch()
            self._classifier = classifier
            self._classifier_model_id = model_name
            return classifier

    def _sample_page_numbers(self, page_count: int) -> list[int]:
        sample_count = min(max(self._settings.rotation_detector_sample_pages, 1), max(page_count, 1))
        if page_count <= sample_count:
            return list(range(1, page_count + 1))

        positions = {1, page_count}
        if sample_count > 2:
            step = (page_count - 1) / (sample_count - 1)
            for sample_index in range(sample_count):
                positions.add(int(round(1 + sample_index * step)))
        return sorted(page for page in positions if 1 <= page <= page_count)

    def _choose_rotation(self, detections: list[dict]) -> int | None:
        qualified = self._qualified_detections(detections)
        if not qualified:
            return None

        counts: dict[int, int] = {}
        confidences: dict[int, list[float]] = {}
        for item in qualified:
            rotation = int(item["rotation"]) % 360
            if rotation == 0:
                continue
            counts[rotation] = counts.get(rotation, 0) + 1
            confidences.setdefault(rotation, []).append(float(item["confidence"]))

        if not counts:
            return None

        dominant_rotation = max(counts, key=counts.get)
        consensus = counts[dominant_rotation] / len(qualified)
        average_confidence = sum(confidences[dominant_rotation]) / len(confidences[dominant_rotation])
        if consensus < self._settings.rotation_detector_min_consensus:
            return None
        if average_confidence < self._settings.rotation_detector_min_confidence:
            return None
        return dominant_rotation

    def _qualified_detections(self, detections: list[dict]) -> list[dict]:
        return [
            item
            for item in detections
            if item["confidence"] >= self._settings.rotation_detector_min_confidence
        ]

    def _should_reverse_page_order(self, rotation: int, detections: list[dict]) -> bool:
        if not self._settings.rotation_reverse_page_order_on_180:
            return False
        if rotation % 360 != 180:
            return False
        qualified = [
            item
            for item in detections
            if item["confidence"] >= self._settings.rotation_detector_min_confidence
        ]
        if len(qualified) < 2:
            return False
        return all(int(item["rotation"]) % 360 == 180 for item in qualified)

    def _rotate_pdf(
        self,
        source: Path,
        rotation: int,
        *,
        page_rotations: dict[int, int] | None = None,
        reverse_page_order: bool = False,
    ) -> Path:
        import fitz
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(prefix=f"{source.stem}.normalized-{rotation}-", suffix=".pdf", delete=False) as handle:
            target = Path(handle.name)
        document = fitz.open(source)
        target_document = fitz.open()
        try:
            page_indexes = range(document.page_count - 1, -1, -1) if reverse_page_order else range(document.page_count)
            for page_index in page_indexes:
                target_document.insert_pdf(document, from_page=page_index, to_page=page_index)
            source_page_numbers = list(range(1, document.page_count + 1))
            if reverse_page_order:
                source_page_numbers.reverse()
            for target_index, page in enumerate(target_document):
                source_page_number = source_page_numbers[target_index]
                page_rotation = (page_rotations or {}).get(source_page_number, rotation)
                page.set_rotation((page.rotation + page_rotation) % 360)
            target_document.save(str(target))
        finally:
            target_document.close()
            document.close()
        return target

    @contextmanager
    def _warmup_lock(self):
        self._warmup_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._warmup_lock_path.open("a+b") as handle:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _sanitize_model_name(self, model_name: str) -> str:
        return "".join(ch if ch.isalnum() else "-" for ch in model_name).strip("-") or "default"
