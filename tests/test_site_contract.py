"""The page and the data have to agree.

Nothing here renders anything. These tests check the contract between what
`app.js` reaches for and what the build actually produces, because the failure
mode otherwise is a blank section in a browser and no error anywhere - the worst
kind of bug to find late, and the easiest kind to catch early.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
APP = SITE / "app.js"
INDEX = SITE / "index.html"
DATA = SITE / "data" / "leaveby.json"

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="run the data_prep stages first")


@pytest.fixture(scope="module")
def payload():
    return json.loads(DATA.read_text())


def test_every_id_app_js_reads_exists_in_the_html():
    wanted = set(re.findall(r'el\("([^"]+)"\)', APP.read_text()))
    html = INDEX.read_text()
    present = set(re.findall(r'id="([^"]+)"', html))
    assert wanted, "no element lookups found - has app.js changed shape?"
    assert wanted <= present, f"app.js reads ids the page does not define: {wanted - present}"


def test_app_js_parses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    result = subprocess.run([node, "--check", str(APP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_data_file_the_page_fetches_is_the_one_we_build():
    assert 'fetch("data/leaveby.json")' in APP.read_text()


def test_top_level_keys_the_page_uses(payload):
    for key in ("airports", "blocks"):
        assert key in payload


def test_block_labels_cover_every_block_the_build_emits(payload):
    labelled = set(re.findall(r"^\s+(\w+): \"", APP.read_text(), re.M))
    missing = set(payload["blocks"]) - labelled
    assert not missing, f"blocks with no label in app.js: {missing}"


def test_every_zone_has_the_fields_the_page_renders(payload):
    checked = 0
    for airport, zones in payload["airports"].items():
        for zone_id, zone in zones.items():
            assert "zone" in zone and "borough" in zone and "blocks" in zone
            if "via" in zone:
                for field in ("station", "route", "link"):
                    assert field in zone["via"], f"{airport} {zone_id} via missing {field}"
            for block, cell in zone["blocks"].items():
                assert block in payload["blocks"]
                assert "verdict" in cell and "leave_by" in cell
                for mode in ("car", "transit"):
                    if cell[mode] is not None:
                        assert "p50" in cell[mode] and "p90" in cell[mode]
                        assert cell[mode]["p50"] <= cell[mode]["p90"]
                checked += 1
    assert checked > 100, f"only {checked} cells - the build looks thin"


def test_a_cell_always_has_at_least_one_mode(payload):
    """A row with neither bar would render as two empty tracks and no verdict."""
    for zones in payload["airports"].values():
        for zone in zones.values():
            for cell in zone["blocks"].values():
                assert cell["car"] or cell["transit"]


def test_every_verdict_is_one_the_page_can_phrase(payload):
    phrased = {"car", "transit", "too close to call", "car only", "transit only"}
    seen = {
        cell["verdict"]
        for zones in payload["airports"].values()
        for zone in zones.values()
        for cell in zone["blocks"].values()
    }
    assert seen <= phrased, f"verdicts the page has no sentence for: {seen - phrased}"
