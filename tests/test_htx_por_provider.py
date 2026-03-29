from __future__ import annotations

import io
import unittest
import zipfile
from datetime import datetime, timezone

from btc_exchange_intel_agent.providers.por_htx import HtxPorProvider


def _build_xlsx_bytes() -> bytes:
    shared = [
        "coin",
        "snapshot height",
        "balance",
        "address",
        "message",
        "signature",
        "BTC(ALL)",
        "-",
        "21362.98",
        "BTC",
        "143gLvWYUojXaWZRrxquRKpVNTkhmr415B",
        "938735",
        "7560.7",
        "huobi",
        "SIG1",
        "1HckjUpRGcrrRAtFaaCAUaGjsPx9oYmLaZ",
        "8.38",
        "King will be back!",
        "SIG2",
        "WBTC-ERC20",
        "0x18709e89bd403f470088abdacebe86cc60dda12e",
        "24355911",
        "1212.72",
        "SIG3",
    ]
    sst_entries = "".join(f"<si><t>{value}</t></si>" for value in shared)
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">{sst_entries}</sst>'
    )
    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>1</v></c>
      <c r="C1" t="s"><v>2</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>6</v></c>
      <c r="B2" t="s"><v>7</v></c>
      <c r="C2" t="s"><v>8</v></c>
    </row>
    <row r="40">
      <c r="A40" t="s"><v>0</v></c>
      <c r="B40" t="s"><v>3</v></c>
      <c r="C40" t="s"><v>1</v></c>
      <c r="D40" t="s"><v>2</v></c>
      <c r="E40" t="s"><v>4</v></c>
      <c r="F40" t="s"><v>5</v></c>
    </row>
    <row r="41">
      <c r="A41" t="s"><v>9</v></c>
      <c r="B41" t="s"><v>10</v></c>
      <c r="C41" t="s"><v>11</v></c>
      <c r="D41" t="s"><v>12</v></c>
      <c r="E41" t="s"><v>13</v></c>
      <c r="F41" t="s"><v>14</v></c>
    </row>
    <row r="42">
      <c r="A42" t="s"><v>9</v></c>
      <c r="B42" t="s"><v>15</v></c>
      <c r="C42" t="s"><v>11</v></c>
      <c r="D42" t="s"><v>16</v></c>
      <c r="E42" t="s"><v>17</v></c>
      <c r="F42" t="s"><v>18</v></c>
    </row>
    <row r="43">
      <c r="A43" t="s"><v>19</v></c>
      <c r="B43" t="s"><v>20</v></c>
      <c r="C43" t="s"><v>21</v></c>
      <c r="D43" t="s"><v>22</v></c>
      <c r="E43" t="s"><v>13</v></c>
      <c r="F43" t="s"><v>23</v></c>
    </row>
  </sheetData>
</worksheet>
"""
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="huobi_por" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>
"""
    root_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


class HtxPorProviderTests(unittest.TestCase):
    def test_extract_versions_from_nested_payload(self) -> None:
        provider = HtxPorProvider(None)
        payload = {
            "code": 200,
            "data": {
                "data": [
                    {"auditNo": "20260201"},
                    {"auditNo": "20260301"},
                ],
                "latestVersion": "20260301",
            },
        }

        self.assertEqual(provider._extract_versions(payload), ["20260301", "20260201"])

    def test_extract_from_xlsx_bytes_yields_only_btc_rows(self) -> None:
        provider = HtxPorProvider(None)
        items = provider._extract_from_xlsx_bytes(
            _build_xlsx_bytes(),
            {
                "version": "20260301",
                "download_url": "https://github.com/huobiapi/Tool-Node.js-VerifyAddress/raw/por_20260301/snapshot/huobi_por.xlsx",
            },
            datetime.now(timezone.utc),
            set(),
        )

        self.assertEqual([item.address for item in items], [
            "143gLvWYUojXaWZRrxquRKpVNTkhmr415B",
            "1HckjUpRGcrrRAtFaaCAUaGjsPx9oYmLaZ",
        ])
        self.assertTrue(all(item.source_type == "official_por" for item in items))
        self.assertTrue(all(item.entity_name_normalized == "huobi" for item in items))
