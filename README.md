# MCP Zscaler ZIA IPs

Python MCP server and client for looking up Zscaler ZIA registered-user IP ranges by location.

The server is intentionally conservative: it only returns CIDRs from columns/fields that are labeled for registered users and ignores non-registered-user IP columns.

## Setup

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Data source

By default, the server uses the Zscaler CENR API behind:

```text
https://config.zscaler.com/zscaler.net/cenr
```

That page is a JavaScript app, so the server reads the backing JSON endpoint directly:

```text
https://config.zscaler.com/api/getdata/zscaler.net/all/cenr?site=config.zscaler.com
```

For the Zscaler CENR data, rows marked `Not Ready for Use` are excluded.

You can also use a local file:

```bash
export ZIA_IP_DATA_PATH=/path/to/zscaler-zia-ips.csv
```

or a URL:

```bash
export ZIA_IP_SOURCE_URL="https://example.com/zscaler-zia-ip-list"
```

Passing `https://config.zscaler.com/zscaler.net/cenr` is supported; it is automatically translated to the backing API URL.

Supported input formats:

- CSV with a location column and a registered-user CIDR/IP column
- JSON list of records with location/name and registered CIDR fields
- HTML tables with location and registered-user IP columns

The parser accepts a range of common header names, including `Location`, `Data Center`, `Registered Users`, and `Registered User IPs`. It intentionally does not treat generic `CIDR` columns as registered-user data unless the column header also says `registered`.

## Run the MCP server

```bash
zia-ip-mcp-server
```

## Query with the bundled client

```bash
zia-ip-mcp-client "miami 3"
```

Pretty JSON output:

```bash
zia-ip-mcp-client "miami 3" --json
```

## MCP tools

`lookup_registered_zia_ips`

Find registered-user CIDR/IP entries for a location query.

Arguments:

- `query`: location text, for example `miami 3`
- `limit`: maximum number of location matches

`list_zia_locations`

List known locations, optionally filtered by search text.

Arguments:

- `search`: optional text filter
- `limit`: maximum rows
