import pytest
import unittest.mock as mock
from app.services.admin_audit_service import mask_secret
from app.services.asterisk_config_generator import validate_asterisk_config_syntax
from app.services.call_admission_control import reconcile_active_counters

def test_credentials_masking():
    # Test typical tokens and passwords
    assert mask_secret("sk-proj-1234567890abcdef") == "sk-********cdef"
    assert mask_secret("supersecretpassword123") == "sup********d123"
    assert mask_secret("short") == "********"
    assert mask_secret("") == ""

def test_config_syntax_validation():
    # Healthy configs
    pjsip_good = "[endpoint]\ntype=endpoint\n"
    ext_good = "[context]\nexten => s,1,NoOp()\n"
    assert validate_asterisk_config_syntax(pjsip_good, ext_good) is None
    
    # Bracket mismatch
    pjsip_bad = "[endpoint\ntype=endpoint\n"
    assert "bracket mismatch" in validate_asterisk_config_syntax(pjsip_bad, ext_good).lower()
    
    # Invalid extension line
    ext_bad = "[context]\ninvalid_keyword => s,1,NoOp()\n"
    assert "invalid line format" in validate_asterisk_config_syntax(pjsip_good, ext_bad).lower()

@mock.patch("app.services.call_admission_control.redis_client")
def test_drift_reconciliation(mock_redis):
    # Setup mock Redis scan_iter & get calls
    mock_redis.scan_iter.side_effect = lambda pat: [
        "call:uuid-1:reservation",
        "call:uuid-2:reservation"
    ] if "reservation" in pat else [
        "workspace:ws-123:active_calls"
    ]
    
    mock_redis.get.side_effect = lambda k: {
        "call:uuid-1:reservation": '{"workspace_id": "ws-123", "agent_id": "ag-1", "direction": "inbound", "incremented": {"workspace": true, "agent": true}}',
        "call:uuid-2:reservation": '{"workspace_id": "ws-123", "agent_id": "ag-1", "direction": "inbound", "incremented": {"workspace": true, "agent": true}}',
        "workspace:ws-123:active_calls": "5"
    }.get(k)
    
    # Run reconciliation
    report = reconcile_active_counters("ws-123")
    
    assert report["success"] is True
    assert report["fixed"] is True
    assert report["active_reservations"] == 2
    assert report["before"]["workspace_active_calls"] == 5
    assert report["after"]["workspace_active_calls"] == 2
    
    # Verify set was called to correct the count
    mock_redis.set.assert_any_call("workspace:ws-123:active_calls", 2)
