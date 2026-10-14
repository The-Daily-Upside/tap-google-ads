import importlib.util
import unittest
from pathlib import Path

_GAQL_PATH = Path(__file__).resolve().parents[1] / "tap_google_ads" / "gaql.py"
_SPEC = importlib.util.spec_from_file_location("tap_gaql", _GAQL_PATH)
_GAQL = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_GAQL)
parse_unrecognized_fields = _GAQL.parse_unrecognized_fields
parse_incompatible_field_pairs = _GAQL.parse_incompatible_field_pairs
parse_segments_with_unsupported_metrics = (
    _GAQL.parse_segments_with_unsupported_metrics
)
choose_incompatible_field_to_drop = _GAQL.choose_incompatible_field_to_drop
search_with_unrecognized_field_pruning = (
    _GAQL.search_with_unrecognized_field_pruning
)


class _ErrorCode:
    def __init__(self, query_error):
        self.query_error = query_error


class _GoogleAdsError:
    def __init__(self, message, query_error="QueryError.UNRECOGNIZED_FIELD"):
        self.message = message
        self.error_code = _ErrorCode(query_error)


class _Failure:
    def __init__(self, errors):
        self.errors = errors


class ParseUnrecognizedFieldsTest(unittest.TestCase):
    def test_parses_field_from_api_message(self):
        message = (
            "Unrecognized field in the query: "
            "'customer.video_customer.third_party_integration_partners."
            "conversion_attribution_integration_partners'."
        )
        exc = type("Exc", (), {"failure": _Failure([_GoogleAdsError(message)])})()
        fields = parse_unrecognized_fields(exc)
        self.assertEqual(
            fields,
            [
                "customer.video_customer.third_party_integration_partners."
                "conversion_attribution_integration_partners"
            ],
        )

    def test_ignores_non_query_errors(self):
        exc = type(
            "Exc",
            (),
            {
                "failure": _Failure(
                    [_GoogleAdsError("Some other error", query_error="QueryError.BAD_VALUE")]
                )
            },
        )()
        self.assertEqual(parse_unrecognized_fields(exc), [])

    def test_parses_incompatible_field_pairs(self):
        message = (
            "The following pairs of fields may not be selected together: "
            "'segments.click_type' and 'segments.conversion_adjustment', "
            "'segments.hour' and 'segments.slot'."
        )
        exc = type("Exc", (), {"failure": _Failure([_GoogleAdsError(message)])})()
        pairs = parse_incompatible_field_pairs(exc)
        self.assertEqual(
            pairs,
            [
                ("segments.click_type", "segments.conversion_adjustment"),
                ("segments.hour", "segments.slot"),
            ],
        )

    def test_parses_segments_with_unsupported_metrics(self):
        message = (
            "Cannot select the following segments because at least one "
            "unsupported metric is found in SELECT or WHERE clause: "
            "'segments.ad_network_type'(unsupported metrics: 'clicks'), "
            "'segments.slot'(unsupported metrics: 'clicks')."
        )
        exc = type("Exc", (), {"failure": _Failure([_GoogleAdsError(message)])})()
        segments = parse_segments_with_unsupported_metrics(exc)
        self.assertEqual(
            segments,
            ["segments.ad_network_type", "segments.slot"],
        )

    def test_chooses_segment_to_drop_over_metric(self):
        drop = choose_incompatible_field_to_drop(
            "segments.click_type", "metrics.clicks"
        )
        self.assertEqual(drop, "segments.click_type")

    def test_pruning_retries_without_bad_field(self):
        bad_field = "customer.removed_field"
        selected = {bad_field, "customer.id"}

        def build_query(fields):
            return "SELECT " + ",".join(sorted(fields))

        calls = {"count": 0}

        class FakeGoogleAdsException(Exception):
            def __init__(self, errors):
                self.failure = _Failure(errors)

        def fake_make_request(_gas, query, _customer_id, _config=None):
            calls["count"] += 1
            if bad_field in query:
                message = f"Unrecognized field in the query: '{bad_field}'."
                raise FakeGoogleAdsException([_GoogleAdsError(message)])
            return ["ok"]

        result = search_with_unrecognized_field_pruning(
            gas=None,
            build_query=build_query,
            selected_fields=selected,
            customer_id="1",
            make_request=fake_make_request,
        )
        self.assertEqual(result, ["ok"])
        self.assertEqual(calls["count"], 2)
        self.assertNotIn(bad_field, selected)
        self.assertIn("customer.id", selected)

    def test_pruning_resolves_incompatible_segment_pairs(self):
        selected = {
            "segments.date",
            "segments.click_type",
            "segments.conversion_adjustment",
            "metrics.clicks",
        }

        def build_query(fields):
            return "SELECT " + ",".join(sorted(fields))

        message = (
            "The following pairs of fields may not be selected together: "
            "'segments.click_type' and 'segments.conversion_adjustment'."
        )

        class FakeGoogleAdsException(Exception):
            def __init__(self, errors):
                self.failure = _Failure(errors)

        calls = {"count": 0}

        def fake_make_request(_gas, query, _customer_id, _config=None):
            calls["count"] += 1
            if (
                "segments.click_type" in query
                and "segments.conversion_adjustment" in query
            ):
                raise FakeGoogleAdsException([_GoogleAdsError(message)])
            return ["ok"]

        result = search_with_unrecognized_field_pruning(
            gas=None,
            build_query=build_query,
            selected_fields=selected,
            customer_id="1",
            make_request=fake_make_request,
        )
        self.assertEqual(result, ["ok"])
        self.assertEqual(calls["count"], 2)
        self.assertNotIn("segments.click_type", selected)
        self.assertIn("segments.conversion_adjustment", selected)
        self.assertIn("metrics.clicks", selected)
        self.assertIn("segments.date", selected)


if __name__ == "__main__":
    unittest.main()
