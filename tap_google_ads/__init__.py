#!/usr/bin/env python3
import logging
import os
import singer
from singer import utils
from tap_google_ads.client import validate_customer_config
from tap_google_ads.discover import create_resource_schema
from tap_google_ads.discover import do_discover
from tap_google_ads.sync import do_sync


LOGGER = singer.get_logger()


REQUIRED_CONFIG_KEYS = [
    "start_date",
]

OAUTH_CONFIG_KEYS = [
    "oauth_client_id",
    "oauth_client_secret",
    "refresh_token",
]


def validate_auth_config(config):
    json_key_file_path = (config.get("json_key_file_path") or "").strip()
    if json_key_file_path:
        if not os.path.isfile(json_key_file_path):
            raise RuntimeError(
                f"json_key_file_path not found: {json_key_file_path}"
            )
        return
    missing = [key for key in OAUTH_CONFIG_KEYS if not config.get(key)]
    if missing:
        raise RuntimeError(
            "Set json_key_file_path for service account auth, "
            f"or provide OAuth settings: {', '.join(missing)}"
        )


def main_impl():
    args = utils.parse_args(REQUIRED_CONFIG_KEYS)
    validate_auth_config(args.config)
    validate_customer_config(args.config)
    resource_schema = create_resource_schema(args.config)
    state = {}

    if args.state:
        state.update(args.state)
    if args.discover:
        do_discover(resource_schema)
        LOGGER.info("Discovery complete")
    elif args.catalog:
        do_sync(args.config, args.catalog.to_dict(), resource_schema, state)
        LOGGER.info("Sync Completed")
    else:
        LOGGER.info("No properties were selected")

def main():

    google_logger = logging.getLogger("google")
    google_logger.setLevel(level=logging.CRITICAL)

    try:
        main_impl()
    except Exception as e:
        for line in str(e).splitlines():
            LOGGER.critical(line)
        raise e


if __name__ == "__main__":
    main()
