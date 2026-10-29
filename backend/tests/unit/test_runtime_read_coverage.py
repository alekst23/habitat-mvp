from aicl.agent_runtime.read_coverage import merged_ranges, read_span, request_covered


def test_actual_read_coverage_merges_overlap_without_conflating_projections_or_inventing_data():
    request = {"ref": "source-ref", "source_index": 0, "public_preview": True, "field": "text"}

    def span(offset, text, total=12):
        return read_span({**request, "offset": offset, "max_chars": 4000},
                         {"error": None, "ref": "source-ref", "source_index": 0,
                          "text": text, "total_chars": total})

    spans = [span(0, "abcde"), span(3, "defghi")]
    assert merged_ranges(spans) == [[0, 9]]
    assert request_covered({**request, "offset": 2, "max_chars": 7}, spans)
    assert not request_covered({**request, "offset": 2, "max_chars": 8}, spans)
    assert not request_covered({**request, "source_index": 1, "max_chars": 3}, spans)
    assert not request_covered({"ref": "source-ref", "source_index": 0, "max_chars": 3}, spans)
    assert request_covered({**request, "offset": 12, "max_chars": 4000}, spans)
    assert read_span(request, {"error": "failed", "ref": "source-ref", "text": "", "total_chars": 0}) is None
    assert span(11, "overflow") is None
