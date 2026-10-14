import json

from google.ads.googleads.client import GoogleAdsClient

from tap_google_ads.api_version import GOOGLE_ADS_API_VERSION


def parse_login_customer_ids(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError as err:
            raise RuntimeError(
                "login_customer_ids must be valid JSON (quote the value in .env)"
            ) from err
    raise RuntimeError("login_customer_ids must be a list or JSON string")


def _normalize_customer_id(value):
    return str(value).replace("-", "").strip()


def normalize_customer_entry(customer, index=0):
    """Return {customerId, loginCustomerId} (Meltano may use snake_case keys)."""
    customer_id = customer.get("customerId", customer.get("customer_id"))
    login_customer_id = customer.get(
        "loginCustomerId", customer.get("login_customer_id")
    )
    if customer_id is None or str(customer_id).strip() == "":
        raise RuntimeError(
            f"login_customer_ids[{index}] is missing customerId (or customer_id)"
        )
    if login_customer_id is None or str(login_customer_id).strip() == "":
        raise RuntimeError(
            f"login_customer_ids[{index}] is missing loginCustomerId "
            "(or login_customer_id — set this to your MCC id)"
        )
    return {
        "customerId": _normalize_customer_id(customer_id),
        "loginCustomerId": _normalize_customer_id(login_customer_id),
    }


def validate_login_customer_ids(config):
    customers = parse_login_customer_ids(config.get("login_customer_ids"))
    if not customers:
        raise RuntimeError(
            "login_customer_ids must contain at least one "
            '{"customerId": "...", "loginCustomerId": "..."} object'
        )
    return [normalize_customer_entry(customer, index=i) for i, customer in enumerate(customers)]


def resolve_customers(config):
    """Single-account config uses customer_id; multi-account uses login_customer_ids.

    When ``login_customer_id`` is set with ``customer_id``, queries run as the MCC
    (login) against the client account (customer_id).
    """
    single = config.get("customer_id")
    if single is not None and str(single).strip() != "":
        customer_id = _normalize_customer_id(single)
        login_override = (config.get("login_customer_id") or "").strip()
        if login_override:
            login_customer_id = _normalize_customer_id(login_override)
        else:
            login_customer_id = customer_id
        return [{"customerId": customer_id, "loginCustomerId": login_customer_id}]
    return validate_login_customer_ids(config)


def validate_customer_config(config):
    single = (config.get("customer_id") or "").strip()
    if single:
        _normalize_customer_id(single)
        return
    if not parse_login_customer_ids(config.get("login_customer_ids")):
        raise RuntimeError(
            "Set customer_id (one Google Ads account, no dashes) or login_customer_ids "
            "for multiple accounts / MCC client access"
        )
    validate_login_customer_ids(config)


def default_login_customer_id(config):
    customers = resolve_customers(config)
    if not customers:
        return None
    login_id = customers[0]["loginCustomerId"]
    customer_id = customers[0]["customerId"]
    if login_id == customer_id:
        return None
    return login_id


def create_sdk_client(config, login_customer_id=None):
    CONFIG = {
        "use_proto_plus": False,
    }

    developer_token = (config.get("developer_token") or "").strip()
    if developer_token:
        CONFIG["developer_token"] = developer_token

    json_key_file_path = (config.get("json_key_file_path") or "").strip()
    if json_key_file_path:
        CONFIG["json_key_file_path"] = json_key_file_path
    else:
        CONFIG["client_id"] = config["oauth_client_id"]
        CONFIG["client_secret"] = config["oauth_client_secret"]
        CONFIG["refresh_token"] = config["refresh_token"]

    if login_customer_id is not None and str(login_customer_id).strip() != "":
        CONFIG["login_customer_id"] = str(login_customer_id).replace("-", "")

    sdk_client = GoogleAdsClient.load_from_dict(CONFIG)
    sdk_client.version = GOOGLE_ADS_API_VERSION
    return sdk_client
