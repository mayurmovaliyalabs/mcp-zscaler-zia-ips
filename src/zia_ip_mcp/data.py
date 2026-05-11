from __future__ import annotations

import csv
import html
import ipaddress
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_ZSCALER_CENR_URL = (
    "https://config.zscaler.com/api/getdata/zscaler.net/all/cenr?site=config.zscaler.com"
)

CIDR_OR_IP_RE = re.compile(
    r"(?<![\w.:/-])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![\w.:/-])"
)

LOCATION_HEADERS = {
    "location",
    "locations",
    "data center",
    "datacenter",
    "city",
    "cloud",
    "site",
    "name",
}

REGISTERED_HEADERS = {
    "registered users",
    "registered user",
    "registered user ips",
    "registered users ips",
    "registered ip",
    "registered ips",
    "registered cidr",
    "registered cidrs",
    "registered users cidr",
    "registered users cidrs",
}


@dataclass(frozen=True)
class ZiaIpEntry:
    location: str
    registered_ips: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "registered_ips": list(self.registered_ips),
            "source": self.source,
        }


class ZiaIpDataError(RuntimeError):
    pass


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: Optional[list[list[str]]] = None
        self._current_row: Optional[list[str]] = None
        self._current_cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(html.unescape(f"&#{name};"))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            text = normalize_cell(" ".join(self._current_cell))
            self._current_row.append(text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if any(self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None


def normalize_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_header(value: object) -> str:
    text = normalize_cell(value).lower()
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"[^a-z0-9 /]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_query(value: str) -> str:
    text = normalize_cell(value).lower()
    text = re.sub(r"\b(iii)\b", "3", text)
    text = re.sub(r"\b(ii)\b", "2", text)
    text = re.sub(r"\b(i)\b", "1", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def extract_valid_ips(value: object) -> tuple[str, ...]:
    found: list[str] = []
    for candidate in extract_ip_candidates(value):
        try:
            if "/" in candidate:
                found.append(str(ipaddress.ip_network(candidate, strict=False)))
            else:
                found.append(str(ipaddress.ip_address(candidate)))
        except ValueError:
            continue
    return tuple(dict.fromkeys(found))


def extract_ip_candidates(value: object) -> tuple[str, ...]:
    text = str(value or "")
    candidates = list(CIDR_OR_IP_RE.findall(text))
    for token in re.split(r"[\s,;()<>\"']+", text):
        token = token.strip("[]{}")
        if ":" in token:
            candidates.append(token)
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def is_location_header(value: object) -> bool:
    header = normalize_header(value)
    return header in LOCATION_HEADERS or header.endswith(" location")


def is_registered_header(value: object) -> bool:
    header = normalize_header(value)
    if "non registered" in header or "nonregistered" in header or "unregistered" in header:
        return False
    return (
        header in REGISTERED_HEADERS
        or ("registered" in header and ("ip" in header or "cidr" in header or "range" in header))
    )


def load_entries() -> list[ZiaIpEntry]:
    data_path = os.getenv("ZIA_IP_DATA_PATH")
    source_url = os.getenv("ZIA_IP_SOURCE_URL")

    if data_path:
        path = Path(data_path).expanduser()
        if not path.exists():
            raise ZiaIpDataError(f"ZIA_IP_DATA_PATH does not exist: {path}")
        return load_entries_from_text(path.read_text(encoding="utf-8"), str(path))

    if source_url:
        return load_entries_from_url(source_url)

    return load_entries_from_url(DEFAULT_ZSCALER_CENR_URL)


def load_entries_from_url(source_url: str) -> list[ZiaIpEntry]:
    source_url = normalize_zscaler_source_url(source_url)
    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "zia-ip-mcp/0.1"},
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
    return load_entries_from_text(body, source_url)


def normalize_zscaler_source_url(source_url: str) -> str:
    if source_url.rstrip("/") == "https://config.zscaler.com/zscaler.net/cenr":
        return DEFAULT_ZSCALER_CENR_URL
    return source_url


def load_entries_from_text(text: str, source: str) -> list[ZiaIpEntry]:
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return _load_json(stripped, source)
    if "<table" in stripped.lower() or "<html" in stripped.lower():
        return _load_html(stripped, source)
    return _load_csv(stripped, source)


def find_entries(entries: Iterable[ZiaIpEntry], query: str, limit: int = 10) -> list[ZiaIpEntry]:
    normalized_query = normalize_query(query)
    if not normalized_query:
        return []

    scored: list[tuple[int, ZiaIpEntry]] = []
    query_parts = set(normalized_query.split())
    for entry in entries:
        location_key = normalize_query(entry.location)
        location_parts = set(location_key.split())
        if normalized_query == location_key:
            score = 0
        elif normalized_query in location_key:
            score = 1
        elif query_parts and query_parts.issubset(location_parts):
            score = 2
        elif query_parts & location_parts:
            score = 3
        else:
            continue
        scored.append((score, entry))

    scored.sort(key=lambda item: (item[0], item[1].location.lower()))
    if scored and scored[0][0] == 0:
        scored = [item for item in scored if item[0] == 0]
    elif any(score <= 2 for score, _ in scored):
        scored = [item for item in scored if item[0] <= 2]
    return [entry for _, entry in scored[: max(1, limit)]]


def _load_csv(text: str, source: str) -> list[ZiaIpEntry]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        return []

    location_field = _first_matching(reader.fieldnames, is_location_header)
    registered_fields = [name for name in reader.fieldnames if is_registered_header(name)]
    return _entries_from_dict_rows(reader, location_field, registered_fields, source)


def _load_json(text: str, source: str) -> list[ZiaIpEntry]:
    payload = json.loads(text)
    zscaler_entries = _load_zscaler_cenr_json(payload, source)
    if zscaler_entries:
        return zscaler_entries

    if isinstance(payload, dict):
        records = payload.get("items") or payload.get("locations") or payload.get("data") or []
    else:
        records = payload
    if not isinstance(records, list):
        raise ZiaIpDataError("JSON data must be a list, or an object with items/locations/data list.")

    all_keys = sorted({key for record in records if isinstance(record, dict) for key in record})
    location_field = _first_matching(all_keys, is_location_header)
    registered_fields = [name for name in all_keys if is_registered_header(name)]
    return _entries_from_dict_rows(records, location_field, registered_fields, source)


def _load_zscaler_cenr_json(payload: Any, source: str) -> list[ZiaIpEntry]:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return []
    modules = payload.get("data")
    if not isinstance(modules, list):
        return []

    table = next((item for item in modules if item.get("id") == "current_dc_body"), None)
    if not isinstance(table, dict):
        return []

    rows = (
        table.get("body", {})
        .get("json", {})
        .get("rows", [])
    )
    records = list(_walk_zscaler_cenr_records(rows))
    grouped: dict[str, list[str]] = {}

    for record in records:
        if _is_not_ready_for_use(record):
            continue
        location = normalize_cell(record.get("location"))
        ips = extract_valid_ips(record.get("ip_address"))
        if not location or not ips:
            continue
        grouped.setdefault(location, [])
        grouped[location].extend(ips)

    return [
        ZiaIpEntry(location=location, registered_ips=tuple(dict.fromkeys(ips)), source=source)
        for location, ips in sorted(grouped.items(), key=lambda item: item[0].lower())
    ]


def _walk_zscaler_cenr_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "location" in value and "ip_address" in value:
            yield value
        for child_key in ("rows", "cols", "data"):
            child = value.get(child_key)
            if child is not None:
                yield from _walk_zscaler_cenr_records(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_zscaler_cenr_records(item)


def _is_not_ready_for_use(record: dict[str, Any]) -> bool:
    notes = record.get("notes") or []
    if not isinstance(notes, list):
        return False
    for note in notes:
        if not isinstance(note, dict):
            continue
        title = normalize_cell(note.get("title")).lower()
        if note.get("id") == 3 or "not ready for use" in title:
            return True
    return False


def _load_html(text: str, source: str) -> list[ZiaIpEntry]:
    parser = _TableParser()
    parser.feed(text)
    entries: list[ZiaIpEntry] = []
    for table in parser.tables:
        if len(table) < 2:
            continue
        headers = table[0]
        location_index = _first_matching_index(headers, is_location_header)
        registered_indexes = [idx for idx, header in enumerate(headers) if is_registered_header(header)]
        if location_index is None or not registered_indexes:
            continue
        for row in table[1:]:
            if location_index >= len(row):
                continue
            location = normalize_cell(row[location_index])
            ips: list[str] = []
            for idx in registered_indexes:
                if idx < len(row):
                    ips.extend(extract_valid_ips(row[idx]))
            if location and ips:
                entries.append(ZiaIpEntry(location=location, registered_ips=tuple(dict.fromkeys(ips)), source=source))
    return entries


def _entries_from_dict_rows(
    records: Iterable[Any],
    location_field: Optional[str],
    registered_fields: list[str],
    source: str,
) -> list[ZiaIpEntry]:
    if not location_field or not registered_fields:
        return []

    entries: list[ZiaIpEntry] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        location = normalize_cell(record.get(location_field))
        ips: list[str] = []
        for field in registered_fields:
            value = record.get(field)
            if isinstance(value, list):
                for item in value:
                    ips.extend(extract_valid_ips(item))
            else:
                ips.extend(extract_valid_ips(value))
        if location and ips:
            entries.append(ZiaIpEntry(location=location, registered_ips=tuple(dict.fromkeys(ips)), source=source))
    return entries


def _first_matching(values: Iterable[str], predicate: Any) -> Optional[str]:
    return next((value for value in values if predicate(value)), None)


def _first_matching_index(values: Iterable[str], predicate: Any) -> Optional[int]:
    return next((idx for idx, value in enumerate(values) if predicate(value)), None)
