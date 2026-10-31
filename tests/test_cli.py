"""The seat's command line: write a morning's report page.

The report is a static page over the ledger, so the only thing this needs to
do is fold a simulated night and write the page, its JSON and its text.
"""

from __future__ import annotations

from core.night.__main__ import main


def test_the_cli_writes_the_morning_report(tmp_path):
    assert main(["--scenario", "clean", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "report.html").exists()
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.txt").exists()


def test_the_cli_writes_the_reboot_morning_too(tmp_path):
    assert main(["--scenario", "reboot", "--out", str(tmp_path)]) == 0
    assert "min lost" in (tmp_path / "report.txt").read_text()


def test_the_cli_lists_the_scenarios_it_knows(capsys):
    assert main(["--list"]) == 0
    printed = capsys.readouterr().out
    assert "clean" in printed
    assert "reboot" in printed
