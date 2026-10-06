from app.main import ReportGate


def test_report_gate_allows_first_report_then_waits_for_interval() -> None:
    gate = ReportGate(interval_seconds=60)

    assert gate.should_report(100.0) is True
    assert gate.should_report(159.9) is False
    assert gate.should_report(160.0) is True
