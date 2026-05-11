from zia_ip_mcp.data import find_entries, load_entries_from_text


def test_csv_loader_ignores_non_registered_user_ips() -> None:
    text = """Location,Registered Users,Non-Registered Users
Miami 3,"198.51.100.0/24, 203.0.113.10/32","192.0.2.0/24"
"""
    entries = load_entries_from_text(text, "fixture.csv")

    assert len(entries) == 1
    assert entries[0].location == "Miami 3"
    assert entries[0].registered_ips == ("198.51.100.0/24", "203.0.113.10/32")
    assert "192.0.2.0/24" not in entries[0].registered_ips


def test_html_loader_finds_registered_user_table_column() -> None:
    text = """
<table>
  <tr><th>Data Center</th><th>Registered User IPs</th><th>Non-Registered User IPs</th></tr>
  <tr><td>Miami III</td><td>198.51.100.0/25<br>198.51.100.128/25</td><td>192.0.2.0/24</td></tr>
</table>
"""
    entries = load_entries_from_text(text, "fixture.html")
    matches = find_entries(entries, "miami 3")

    assert len(matches) == 1
    assert matches[0].registered_ips == ("198.51.100.0/25", "198.51.100.128/25")


def test_zscaler_cenr_loader_excludes_not_ready_for_use_rows() -> None:
    text = """
{
  "status": "success",
  "data": [
    {
      "type": "table",
      "id": "current_dc_body",
      "body": {
        "json": {
          "rows": [
            {
              "region": "Americas",
              "cols": [
                {
                  "title": "Miami III",
                  "data": [
                    {
                      "region": "Americas",
                      "location": "Miami III",
                      "ip_address": "198.51.100.0/24",
                      "notes": []
                    },
                    {
                      "region": "Americas",
                      "location": "Miami III",
                      "ip_address": "192.0.2.0/24",
                      "notes": [{"id": 3, "title": "Not Ready for Use"}]
                    },
                    {
                      "region": "Americas",
                      "location": "Miami III",
                      "ip_address": "2001:db8:1234::/48",
                      "notes": []
                    }
                  ]
                }
              ]
            }
          ]
        }
      }
    }
  ]
}
"""
    entries = load_entries_from_text(text, "fixture-zscaler.json")
    matches = find_entries(entries, "miami 3")

    assert len(matches) == 1
    assert matches[0].registered_ips == ("198.51.100.0/24", "2001:db8:1234::/48")


def test_exact_location_match_does_not_return_other_roman_numeral_matches() -> None:
    text = """Location,Registered Users
Miami III,198.51.100.0/24
Amsterdam III,203.0.113.0/24
"""
    entries = load_entries_from_text(text, "fixture.csv")
    matches = find_entries(entries, "miami 3")

    assert [match.location for match in matches] == ["Miami III"]
