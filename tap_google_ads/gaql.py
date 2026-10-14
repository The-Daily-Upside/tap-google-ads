"""Helpers for Google Ads Query Language (GAQL) search requests."""

import logging
import re

LOGGER = logging.getLogger(__name__)

UNRECOGNIZED_FIELD_MESSAGE_RE = re.compile(
    r"Unrecognized field in the query: '([^']+)'"
)
INCOMPATIBLE_FIELD_PAIR_RE = re.compile(
    r"'([^']+)'\s+and\s+'([^']+)'"
)
UNSUPPORTED_SEGMENT_RE = re.compile(
    r"'(segments\.[^']+)'\(unsupported metrics:"
)

# When two selected fields conflict, drop the one that sorts earlier (segments before metrics).
_FIELD_DROP_PRIORITY = (
    "segments.click_type",
    "segments.conversion_adjustment",
    "segments.conversion_lag_bucket",
    "segments.conversion_or_adjustment_lag_bucket",
    "segments.month_of_year",
    "segments.hour",
    "segments.slot",
    "segments.month",
    "segments.week",
    "segments.quarter",
    "segments.year",
    "segments.day_of_week",
    "segments.external_conversion_source",
    "segments.conversion_action",
    "segments.conversion_action_name",
    "segments.conversion_action_category",
    "segments.ad_network_type",
)


def _field_drop_rank(field_name):
    try:
        return _FIELD_DROP_PRIORITY.index(field_name)
    except ValueError:
        if field_name.startswith("metrics."):
            return len(_FIELD_DROP_PRIORITY) + 100
        if field_name == "segments.date":
            return len(_FIELD_DROP_PRIORITY) + 99
        if field_name.endswith(".id"):
            return len(_FIELD_DROP_PRIORITY) + 98
        if field_name.startswith("segments."):
            return len(_FIELD_DROP_PRIORITY) + 10
        return len(_FIELD_DROP_PRIORITY) + 50


def choose_incompatible_field_to_drop(field_a, field_b):
    """Pick which conflicting GAQL field to remove from the query."""
    rank_a = _field_drop_rank(field_a)
    rank_b = _field_drop_rank(field_b)
    if rank_a != rank_b:
        return field_a if rank_a < rank_b else field_b
    return max(field_a, field_b)


def _iter_google_ads_errors(exception):
    failure = getattr(exception, "failure", None)
    errors = getattr(failure, "errors", None) if failure else None
    if not errors:
        return
    for error in errors:
        yield error


def parse_unrecognized_fields(exception):
    """Return GAQL field names rejected with QueryError.UNRECOGNIZED_FIELD."""
    fields = []
    for error in _iter_google_ads_errors(exception):
        query_error = str(error.error_code.query_error)
        if "UNRECOGNIZED_FIELD" not in query_error:
            continue
        message = error.message or ""
        match = UNRECOGNIZED_FIELD_MESSAGE_RE.search(message)
        if match:
            field_name = match.group(1)
            if field_name not in fields:
                fields.append(field_name)
    return fields


def parse_incompatible_field_pairs(exception):
    """Return pairs of GAQL fields that may not be selected together."""
    pairs = []
    for error in _iter_google_ads_errors(exception):
        message = error.message or ""
        if "may not be selected together" not in message:
            continue
        for match in INCOMPATIBLE_FIELD_PAIR_RE.finditer(message):
            pair = (match.group(1), match.group(2))
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def parse_segments_with_unsupported_metrics(exception):
    """Return segment fields that cannot be queried with the selected metrics."""
    segments = []
    for error in _iter_google_ads_errors(exception):
        message = error.message or ""
        if "unsupported metric" not in message:
            continue
        for match in UNSUPPORTED_SEGMENT_RE.finditer(message):
            segment = match.group(1)
            if segment not in segments:
                segments.append(segment)
    return segments


def search_with_unrecognized_field_pruning(
    gas,
    build_query,
    selected_fields,
    customer_id,
    make_request,
    config=None,
):
    """Run GAQL search, dropping fields the API rejects until the query succeeds."""
    if config is None:
        config = {}

    if not selected_fields:
        raise RuntimeError("No GAQL fields selected for search")

    max_attempts = len(selected_fields) + 1
    query = None

    for _ in range(max_attempts):
        query = build_query(selected_fields)
        try:
            return make_request(gas, query, customer_id, config)
        except Exception as err:
            unrecognized = parse_unrecognized_fields(err)
            incompatible_pairs = parse_incompatible_field_pairs(err)
            unsupported_segments = parse_segments_with_unsupported_metrics(err)

            if not unrecognized and not incompatible_pairs and not unsupported_segments:
                LOGGER.warning("Failed query: %s", query)
                raise

            removed_any = False

            for field_name in unrecognized:
                if field_name in selected_fields:
                    selected_fields.discard(field_name)
                    LOGGER.warning(
                        "Removing unrecognized GAQL field from query: %s",
                        field_name,
                    )
                    removed_any = True

            for field_a, field_b in incompatible_pairs:
                if field_a in selected_fields and field_b in selected_fields:
                    drop = choose_incompatible_field_to_drop(field_a, field_b)
                    selected_fields.discard(drop)
                    LOGGER.warning(
                        "Removing incompatible GAQL field from query: %s "
                        "(conflicts with %s)",
                        drop,
                        field_b if drop == field_a else field_a,
                    )
                    removed_any = True

            for segment in unsupported_segments:
                if segment in selected_fields:
                    selected_fields.discard(segment)
                    LOGGER.warning(
                        "Removing GAQL segment incompatible with selected metrics: %s",
                        segment,
                    )
                    removed_any = True

            if not removed_any:
                LOGGER.warning("Failed query: %s", query)
                raise

            if not selected_fields:
                LOGGER.warning("Failed query: %s", query)
                raise RuntimeError(
                    "All selected fields were rejected by the Google Ads API"
                ) from err

    raise RuntimeError("Exceeded GAQL field-pruning retry limit for search")
