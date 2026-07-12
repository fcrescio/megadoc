from scripts.evaluate_page_artifacts import expected_rotations


def test_expected_rotations_applies_overrides_and_skips_ambiguous_pages():
    payload = {
        "documents": [{
            "case_id": "sample",
            "pages": [1, 2, 3],
            "dominant_rotation": 180,
            "rotations": {"2": 90},
            "ambiguous_pages": [3],
        }]
    }

    assert expected_rotations(payload) == [
        ("sample", 1, 180),
        ("sample", 2, 90),
    ]
